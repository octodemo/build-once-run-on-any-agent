// Assembles everything the Dataforge canvas shows, from real artifacts only:
// the issue and story fixture, the resolved manifest, forge-builder's build
// state, files changed in the metric store, read-only copies of the regional
// DuckDB warehouses, and pull request status from GitHub.
//
// No Copilot SDK imports here, so preview.mjs can serve the same state outside
// a Copilot session. Nothing in this file writes to the project.

import { execFile } from "node:child_process";
import { copyFileSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { basename, join, relative } from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

export const PHASES = [
    "Intake and scoping",
    "Data discovery",
    "Metric design",
    "Schema architecture",
    "Pipeline code",
    "Testing and validation",
    "Deployment and delivery",
];

export const SKILLS = [
    { name: "forge-init", role: "Learns the project" },
    { name: "forge-dbx", role: "Talks to the warehouse" },
    { name: "forge-lint", role: "Applies the house rules" },
    { name: "forge-builder", role: "Runs the seven phases" },
];

const ACTIVE_WINDOW_MS = 90_000;
const WAREHOUSE_TTL_MS = 5_000;
const GITHUB_TTL_MS = 15_000;
const DUCKDB_ENV = { ...process.env, DUCKDB_AGENT_MODE: "0" };

function safeRead(path) {
    try {
        return readFileSync(path, "utf8");
    } catch {
        return null;
    }
}

function safeDir(path) {
    try {
        return readdirSync(path);
    } catch {
        return [];
    }
}

function mtime(path) {
    try {
        return statSync(path).mtimeMs;
    } catch {
        return 0;
    }
}

async function command(file, args, options = {}) {
    try {
        const { stdout } = await run(file, args, { timeout: 15_000, maxBuffer: 8 * 1024 * 1024, ...options });
        return { ok: true, stdout };
    } catch (error) {
        return { ok: false, error: (error.stderr || error.message || String(error)).toString().trim() };
    }
}

async function yamlToJson(path) {
    const result = await command("/usr/bin/ruby", [
        "-ryaml",
        "-rjson",
        "-e",
        "print JSON.generate(YAML.safe_load(File.read(ARGV[0]), aliases: true))",
        path,
    ]);
    if (!result.ok) return null;
    try {
        return JSON.parse(result.stdout);
    } catch {
        return null;
    }
}

function issueBody(markdown) {
    return (markdown || "").replace(/<!--[\s\S]*?-->/g, "").trim();
}

function catalogNames(configPy) {
    const names = [...(configPy || "").matchAll(/_catalog\("([^"]+)"\)/g)].map((m) => m[1]);
    return { source: names[0] || "demo_gold_commerce", target: names[1] || "demo_gold_marketplace_metric_store" };
}

export function createState({ repoRoot, exampleDir }) {
    const storyPath = join(repoRoot, "acceptance", "online-marketplace", "story.json");
    const issuePath = join(exampleDir, "issues", "dispatch-promise.md");
    const seedPath = join(exampleDir, "dataforge.manifest.yaml");
    const resolvedPath = join(exampleDir, "dataforge.manifest.resolved.yaml");
    const warehouseDir = join(exampleDir, "warehouse");

    const skillUse = new Map(SKILLS.map((s) => [s.name, { count: 0, last: 0, source: null }]));
    const activity = [];
    const startedAt = Date.now() - 60_000;
    const requestedView = { name: null, seq: 0 };
    const cache = {
        manifest: { at: 0, value: null },
        warehouse: { at: 0, value: null },
        github: { at: 0, value: null },
    };

    function note(label, kind = "tool") {
        activity.unshift({ at: new Date().toISOString(), kind, label });
        activity.length = Math.min(activity.length, 40);
    }

    function touchSkill(name, how) {
        const entry = skillUse.get(name);
        if (!entry) return;
        entry.count += 1;
        entry.last = Date.now();
        entry.source = how;
    }

    // Called for "skill.invoked" session events.
    function recordSkill(data = {}) {
        if (!skillUse.has(data.name)) return;
        touchSkill(data.name, data.pluginName ? `${data.pluginName} plugin` : "skill");
        note(`${data.name} skill loaded${data.pluginName ? ` from the ${data.pluginName} plugin` : ""}`, "skill");
    }

    // Called for "tool.execution_start" session events. Only short labels are
    // kept; full commands and file contents are never stored.
    function recordTool(data = {}) {
        const args = data.arguments || {};
        const text = typeof args === "string" ? args : JSON.stringify(args);
        const read = text.match(/(forge-(?:init|dbx|lint|builder))\/(?:SKILL\.md|references\/([\w./-]+))/);
        if (read) {
            touchSkill(read[1], "read");
            note(`${read[1]}: read ${read[2] ? `references/${basename(read[2])}` : "SKILL.md"}`);
            return;
        }
        const cmd = typeof args.command === "string" ? args.command : "";
        const zone = cmd.match(/warehouse\/(\w+)\.duckdb/);
        if (/\bduckdb\b/.test(cmd)) {
            touchSkill("forge-dbx", "query");
            note(`forge-dbx: DuckDB ${/INSERT|CREATE|DROP|ALTER/i.test(cmd) ? "write" : "query"}${zone ? ` on ${zone[1]}` : ""}`);
        } else if (/\bgh (issue|pr|label)\b/.test(cmd)) {
            note(`GitHub: gh ${cmd.match(/\bgh (issue|pr|label) (\w+)/)?.slice(1).join(" ") || "command"}`);
        } else if (/verify\.py/.test(cmd)) {
            touchSkill("forge-builder", "checkpoint");
            note(`forge-builder: checkpoint check (${cmd.match(/verify\.py\s+([\w-]+)/)?.[1] || "verify"})`);
        }
    }

    function requestView(name) {
        requestedView.name = name;
        requestedView.seq += 1;
    }

    async function manifest(force) {
        const stamp = mtime(resolvedPath);
        if (!force && cache.manifest.value && cache.manifest.at === stamp) return cache.manifest.value;
        const raw = safeRead(resolvedPath);
        if (!raw) {
            const value = { exists: false };
            cache.manifest = { at: stamp, value };
            return value;
        }
        const parsed = await yamlToJson(resolvedPath);
        const seed = (await yamlToJson(seedPath)) || {};
        const added = seed?.overrides?.naming?.verbs || [];
        let facts = null;
        if (parsed) {
            const zones = parsed.platform?.zones?.map((z) => z.id) || [];
            facts = {
                engine: parsed.platform?.engine,
                deploymentOrder: parsed.platform?.deployment_order || zones,
                sources: (parsed.catalogs?.sources || []).map((c) => c.pattern),
                targets: (parsed.catalogs?.targets || []).map((c) => c.pattern),
                domains: Object.entries(parsed.domains || {}).map(([name, d]) => ({ name, entities: d?.tools || [] })),
                grains: Object.entries(parsed.grains || {}).map(([name, g]) => ({ name, columns: g?.columns || [] })),
                cadences: parsed.cadences || [],
                metricPattern: parsed.naming?.metric_pattern,
                verbs: (parsed.naming?.verbs || []).map((v) => ({ verb: v, fromManifest: added.includes(v) })),
                unsupported: [
                    parsed.orchestration?.supported === false ? `Scheduling: ${parsed.orchestration.unsupported_reason || "not supported"}` : null,
                    parsed.source_metadata?.version_history?.enabled === false
                        ? `Table history: ${parsed.source_metadata.version_history.unsupported_reason || "not supported"}`
                        : null,
                ].filter(Boolean),
            };
        }
        const generated = raw.match(/^#\s*Generated:\s*(.+)$/m)?.[1]?.trim() || null;
        const value = { exists: true, path: relative(repoRoot, resolvedPath), generated, facts, raw };
        cache.manifest = { at: stamp, value };
        return value;
    }

    function storeDomains() {
        const store = join(exampleDir, "marketplace_metric_store");
        return safeDir(store).filter((d) => d !== "common" && !d.startsWith(".") && !d.includes("."));
    }

    function buildStateDirs() {
        const dirs = [
            join(exampleDir, ".build-state"),
            join(exampleDir, "skills", "forge-builder", ".build-state"),
            join(repoRoot, "demos", "dataforge", "skills", "forge-builder", ".build-state"),
            join(repoRoot, ".build-state"),
        ];
        const installed = join(process.env.COPILOT_HOME || join(homedir(), ".copilot"), "installed-plugins");
        for (const market of safeDir(installed)) {
            for (const plugin of safeDir(join(installed, market))) {
                dirs.push(join(installed, market, plugin, "skills", "forge-builder", ".build-state"));
            }
        }
        return dirs;
    }

    function anchor() {
        // A run starts when seed.py rebuilds the warehouse: its files' creation
        // time marks the start, so leftovers from a rehearsal are ignored even
        // after the app restarts.
        const births = safeDir(warehouseDir)
            .filter((f) => f.endsWith(".duckdb"))
            .map((f) => {
                try {
                    return statSync(join(warehouseDir, f)).birthtimeMs;
                } catch {
                    return 0;
                }
            })
            .filter(Boolean);
        return births.length ? Math.min(...births) - 5_000 : startedAt;
    }

    function buildState() {
        const domains = new Set(storeDomains());
        const since = anchor();
        let best = null;
        for (const dir of buildStateDirs()) {
            for (const file of safeDir(dir)) {
                if (!file.endsWith(".json")) continue;
                const path = join(dir, file);
                const when = mtime(path);
                if (when < since || (best && when <= best.when)) continue;
                try {
                    const data = JSON.parse(readFileSync(path, "utf8"));
                    if (data.domain && domains.size && !domains.has(data.domain)) continue;
                    best = { path, when, data };
                } catch {
                    // A half-written file: ignore it until the next poll.
                }
            }
        }
        if (!best) return { found: false };
        const d = best.data;
        return {
            found: true,
            path: best.path.startsWith(repoRoot) ? relative(repoRoot, best.path) : best.path.replace(homedir(), "~"),
            buildId: d.build_id,
            tool: d.folder_name || d.tool_name,
            issue: d.issue_number || null,
            status: d.status,
            currentPhase: d.current_phase ?? null,
            completed: Array.isArray(d.completed_phases) ? d.completed_phases : [],
            metrics: (Array.isArray(d.metrics) ? d.metrics : []).map((m) => ({ name: m.name, status: m.status })),
            deployment: d.deployment || {},
            branch: d.branch || null,
            prUrl: d.pr_url || null,
            blocking: d.blocking || null,
            updatedAt: d.updated_at || null,
        };
    }

    function phases(state) {
        const done = new Set(state.found ? state.completed : []);
        const current = state.found ? state.currentPhase : null;
        return PHASES.map((name, i) => {
            const n = i + 1;
            let status = "pending";
            if (done.has(n)) status = "done";
            else if (current === n || (state.found && !done.has(n) && done.has(n - 1) && state.status !== "completed")) status = "current";
            if (status === "current" && state.blocking) status = "waiting";
            return { n, name, status };
        });
    }

    async function changedFiles() {
        const rel = relative(repoRoot, exampleDir);
        const files = new Map();
        const base = await command("git", ["merge-base", "HEAD", "origin/main"], { cwd: repoRoot });
        if (base.ok) {
            const diff = await command("git", ["diff", "--name-status", base.stdout.trim(), "--", rel], { cwd: repoRoot });
            if (diff.ok) {
                for (const line of diff.stdout.split("\n").filter(Boolean)) {
                    const [code, path] = line.split("\t");
                    files.set(path, code.startsWith("A") ? "added" : "changed");
                }
            }
        }
        const status = await command("git", ["status", "--porcelain=v1", "--untracked-files=all", "--", rel], { cwd: repoRoot });
        if (status.ok) {
            for (const line of status.stdout.split("\n").filter(Boolean)) {
                const code = line.slice(0, 2);
                const path = line.slice(3);
                files.set(path, code.includes("?") || code.includes("A") ? "added" : "changed");
            }
        }
        return [...files.entries()]
            .filter(([path]) => !path.includes("/warehouse/") && !path.endsWith(".duckdb"))
            .map(([path, change]) => ({ path: relative(rel, path) || path, change, when: mtime(join(repoRoot, path)) }))
            .sort((a, b) => b.when - a.when)
            .slice(0, 30);
    }

    async function duckJson(db, sql) {
        return new Promise((resolve) => {
            const child = execFile("duckdb", ["-json", db], { env: DUCKDB_ENV, timeout: 15_000, maxBuffer: 8 * 1024 * 1024 }, (error, stdout, stderr) => {
                if (error) return resolve({ ok: false, error: (stderr || error.message).toString().trim() });
                const text = stdout.trim();
                try {
                    resolve({ ok: true, rows: text ? JSON.parse(text) : [] });
                } catch (parseError) {
                    resolve({ ok: false, error: String(parseError) });
                }
            });
            child.stdin.end(sql);
        });
    }

    async function warehouse(force, story, newEntityHint) {
        if (!force && cache.warehouse.value && Date.now() - cache.warehouse.at < WAREHOUSE_TTL_MS) return cache.warehouse.value;
        const { source, target } = catalogNames(safeRead(join(exampleDir, "marketplace_metric_store", "common", "config.py")));
        const zones = safeDir(warehouseDir).filter((f) => f.endsWith(".duckdb")).map((f) => f.replace(/\.duckdb$/, "")).sort();
        const result = { zones: {}, built: zones.length > 0 };
        for (const zone of zones) {
            // Read a private copy so the canvas never holds a lock on a file the
            // agent may be writing to.
            const tmp = mkdtempSync(join(tmpdir(), "dataforge-canvas-"));
            const copy = join(tmp, `${zone}.duckdb`);
            try {
                copyFileSync(join(warehouseDir, `${zone}.duckdb`), copy);
                if (existsSync(join(warehouseDir, `${zone}.duckdb.wal`))) copyFileSync(join(warehouseDir, `${zone}.duckdb.wal`), `${copy}.wal`);
                const tables = await duckJson(copy, `SELECT table_name FROM information_schema.tables WHERE table_schema = '${target}' ORDER BY 1;`);
                if (!tables.ok) throw new Error(tables.error);
                const entities = [
                    ...new Set(
                        tables.rows
                            .map((r) => r.table_name.match(/^(.+)_Merchant_Metrics_Snapshot_(Daily|Cumulative)$/)?.[1])
                            .filter(Boolean),
                    ),
                ];
                const newEntities = entities.filter((e) => e !== "Order");
                const zoneInfo = { available: true, entities, newEntities, merchants: [], story: null, latest: null };
                const entity = newEntities.includes(newEntityHint) ? newEntityHint : newEntities[0];
                if (entity) {
                    const cumulative = `${target}."${entity}_Merchant_Metrics_Snapshot_Cumulative"`;
                    const latest = await duckJson(
                        copy,
                        `SELECT CAST(MAX(SNAPSHOT_DATE) AS VARCHAR) AS d, COUNT(DISTINCT SNAPSHOT_DATE) AS days FROM ${cumulative};`,
                    );
                    const rows = await duckJson(
                        copy,
                        `SELECT m.merchant_name, t.merchant_id, t.metric_name, t.metric_value
                         FROM ${cumulative} t JOIN ${source}.merchants m USING (merchant_id)
                         WHERE t.SNAPSHOT_DATE = (SELECT MAX(SNAPSHOT_DATE) FROM ${cumulative})
                         ORDER BY 1, 3;`,
                    );
                    if (latest.ok) zoneInfo.latest = { date: latest.rows[0]?.d || null, days: latest.rows[0]?.days || 0, entity };
                    if (rows.ok) {
                        const byMerchant = new Map();
                        for (const row of rows.rows) {
                            const entry = byMerchant.get(row.merchant_id) || { merchantId: row.merchant_id, name: row.merchant_name, metrics: {} };
                            entry.metrics[row.metric_name] = row.metric_value;
                            byMerchant.set(row.merchant_id, entry);
                        }
                        zoneInfo.merchants = [...byMerchant.values()];
                    }
                    if (story && zone === story.merchant.zone) {
                        const daily = `${target}."${entity}_Merchant_Metrics_Snapshot_Daily"`;
                        const lastDay = await duckJson(copy, `SELECT CAST(CAST(MAX(placed_at) AS DATE) AS VARCHAR) AS d FROM ${source}.orders;`);
                        const storyRows = await duckJson(
                            copy,
                            `SELECT CAST(SNAPSHOT_DATE AS VARCHAR) AS d, metric_name, metric_value FROM ${daily}
                             WHERE merchant_id = ${Number(story.merchant.merchant_id)} ORDER BY 1, 2;`,
                        );
                        if (lastDay.ok && storyRows.ok && lastDay.rows[0]?.d) {
                            const end = new Date(`${lastDay.rows[0].d}T00:00:00Z`);
                            const actual = {};
                            for (const row of storyRows.rows) {
                                const day = 7 - Math.round((end - new Date(`${row.d}T00:00:00Z`)) / 86_400_000);
                                if (day < 1 || day > 7) continue;
                                actual[row.metric_name] = actual[row.metric_name] || {};
                                actual[row.metric_name][String(day)] = (actual[row.metric_name][String(day)] || 0) + row.metric_value;
                            }
                            zoneInfo.story = { actual, loadedDays: storyRows.rows.length };
                        }
                    }
                }
                result.zones[zone] = zoneInfo;
            } catch (error) {
                result.zones[zone] = { available: false, note: `Could not read a copy of ${zone}.duckdb yet (${String(error.message || error).slice(0, 120)}). Retrying.` };
            } finally {
                rmSync(tmp, { recursive: true, force: true });
            }
        }
        cache.warehouse = { at: Date.now(), value: result };
        return result;
    }

    function repoSlug() {
        const seed = safeRead(seedPath) || "";
        return seed.match(/^\s*repository:\s*"?([\w.-]+\/[\w.-]+)"?\s*$/m)?.[1] || null;
    }

    async function github(force, state, story) {
        if (!force && cache.github.value && Date.now() - cache.github.at < GITHUB_TTL_MS) return cache.github.value;
        const repo = repoSlug();
        const value = { repo, issue: null, pr: null, error: null };
        if (!repo) {
            value.error = "No repository is set in the manifest.";
            cache.github = { at: Date.now(), value };
            return value;
        }
        const since = anchor();
        const gh = (args) => command("gh", args, { cwd: repoRoot });
        const parse = (result) => {
            if (!result.ok) return null;
            try {
                return JSON.parse(result.stdout);
            } catch {
                return null;
            }
        };

        const issueNumber = state.found && state.issue ? String(state.issue) : null;
        if (issueNumber) {
            value.issue = parse(await gh(["issue", "view", issueNumber, "-R", repo, "--json", "number,title,url,state"]));
        } else {
            // Before forge-builder records the issue, only show one created
            // since the warehouse was last reset, so a rehearsal issue never appears.
            const title = story?.issueTitle || "48-hour dispatch promise";
            const issues = parse(await gh(["issue", "list", "-R", repo, "--state", "all", "--search", `${title} in:title`, "--json", "number,title,url,state,createdAt", "--limit", "10"])) || [];
            value.issue = issues.filter((i) => Date.parse(i.createdAt) >= since).sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0] || null;
        }

        let prNumber = state.found && state.prUrl ? state.prUrl.match(/\/pull\/(\d+)/)?.[1] : null;
        if (!prNumber && state.found && state.branch) {
            const prs = parse(await gh(["pr", "list", "-R", repo, "--state", "all", "--head", state.branch, "--json", "number,createdAt", "--limit", "5"])) || [];
            prNumber = prs.sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0]?.number?.toString() || null;
        }
        if (!prNumber) {
            const prs = parse(await gh(["pr", "list", "-R", repo, "--state", "all", "--search", "dispatch in:title", "--json", "number,createdAt", "--limit", "10"])) || [];
            prNumber = prs.filter((p) => Date.parse(p.createdAt) >= since).sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0]?.number?.toString() || null;
        }
        if (prNumber) {
            const pr = parse(await gh(["pr", "view", prNumber, "-R", repo, "--json", "number,title,url,state,headRefName,isDraft"]));
            if (pr) {
                const checks = parse(await gh(["pr", "checks", prNumber, "-R", repo, "--json", "name,state,bucket,link,workflow"])) || [];
                const comments = parse(await gh(["api", `repos/${repo}/issues/${prNumber}/comments?per_page=100`])) || [];
                const review = [...comments].reverse().find((c) => /Proof Agent Verification/.test(c.body || ""));
                let proofAgent = null;
                if (review) {
                    const verdict = review.body.match(/\*\*(PASS|FAIL|PARTIAL|SKIPPED)\*\*/)?.[1] || "UNKNOWN";
                    const summary = review.body
                        .replace(/<details>[\s\S]*$/m, "")
                        .split("\n")
                        .filter((line) => line.trim() && !/^##|^\*\*(PASS|FAIL|PARTIAL|SKIPPED)\*\*|^[✅❌⚠️⏭️]/.test(line.trim()))
                        .slice(0, 6)
                        .join("\n")
                        .slice(0, 600);
                    proofAgent = { verdict, url: review.html_url, at: review.created_at, summary };
                }
                value.pr = {
                    ...pr,
                    checks: checks.map((c) => ({ name: c.name, workflow: c.workflow, state: c.state, bucket: c.bucket, link: c.link })),
                    proofAgent,
                };
            }
        }
        cache.github = { at: Date.now(), value };
        return value;
    }

    async function snapshot({ force = false } = {}) {
        const storyRaw = safeRead(storyPath);
        const story = storyRaw ? JSON.parse(storyRaw) : null;
        const issueMd = safeRead(issuePath);
        if (story) story.issueTitle = "Track our 48-hour dispatch promise";
        const state = buildState();
        const [manifestInfo, files, warehouseInfo, githubInfo] = await Promise.all([
            manifest(force),
            changedFiles(),
            warehouse(force, story, state.found ? state.tool : null),
            github(force, state, story),
        ]);
        const now = Date.now();
        const skills = SKILLS.map((s) => {
            const use = skillUse.get(s.name);
            return { ...s, uses: use.count, last: use.last || null, active: use.last > 0 && now - use.last < ACTIVE_WINDOW_MS, how: use.source };
        });
        return {
            generatedAt: new Date().toISOString(),
            project: { name: basename(exampleDir), path: relative(repoRoot, exampleDir) },
            requestedView: { ...requestedView },
            question: { issue: { body: issueBody(issueMd), live: githubInfo.issue }, story },
            build: { skills, manifest: manifestInfo, state, phases: phases(state), files, activity: activity.slice(0, 12) },
            proof: { warehouse: warehouseInfo, github: githubInfo, story },
        };
    }

    async function summary() {
        const s = await snapshot({ force: true });
        const st = s.build.state;
        const current = s.build.phases.find((p) => p.status === "current" || p.status === "waiting");
        const lines = [
            st.found
                ? `Build ${st.buildId}: ${st.status}. ${current ? `Phase ${current.n} of 7 (${current.name})${current.status === "waiting" ? ", waiting for a person" : ""}.` : "All phases complete."}`
                : "No forge-builder build state yet.",
            s.build.manifest.exists ? `Resolved manifest present (${s.build.manifest.path}).` : "No resolved manifest yet: run forge-init.",
            `Files changed in the example: ${s.build.files.length}.`,
            s.proof.github.pr
                ? `PR #${s.proof.github.pr.number} (${s.proof.github.pr.state}); Proof Agent: ${s.proof.github.pr.proofAgent?.verdict || "no comment yet"}.`
                : "No pull request yet.",
        ];
        return lines.join("\n");
    }

    return { snapshot, summary, recordSkill, recordTool, requestView };
}
