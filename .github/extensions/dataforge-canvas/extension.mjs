// Dataforge canvas for the GitHub Copilot app.
//
// Shows a live, read-only view of a Dataforge build beside the chat: the
// business question, the four skills and seven phases, and the proof. It reads
// real artifacts only (see state.mjs) and observes skill and tool events from
// the session. The Dataforge skills are unchanged and unaware of this canvas:
// it is the host-specific layer, not part of the portable procedure.

import { existsSync, realpathSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { CanvasError, createCanvas, joinSession } from "@github/copilot-sdk/extension";
import { serve } from "./server.mjs";
import { createState } from "./state.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = realpathSync(resolve(HERE, "..", "..", ".."));
const DEFAULT_PROJECT = "demos/dataforge/examples/online-marketplace";
const VIEWS = ["question", "build", "proof"];

const states = new Map(); // example project directory -> state
const instances = new Map(); // canvas instanceId -> { server, url, project, state }

// Only Dataforge projects inside this repository can be opened: the folder
// must resolve (symlinks included) under the repository root and contain a
// seed manifest.
function projectDir(project) {
    let dir;
    try {
        dir = realpathSync(resolve(REPO_ROOT, project));
    } catch {
        dir = null;
    }
    if (!dir || !(dir === REPO_ROOT || dir.startsWith(REPO_ROOT + sep)) || !existsSync(join(dir, "dataforge.manifest.yaml"))) {
        throw new CanvasError("invalid_project", "The project must be a Dataforge project folder inside this repository.");
    }
    return dir;
}

function stateFor(project) {
    const exampleDir = projectDir(project);
    if (!states.has(exampleDir)) states.set(exampleDir, createState({ repoRoot: REPO_ROOT, exampleDir }));
    return states.get(exampleDir);
}

// Start recording skill and tool activity as soon as the session starts, so the
// canvas can show what happened before it was opened.
try {
    stateFor(DEFAULT_PROJECT);
} catch {
    // The example project is missing in this checkout; the canvas reports it when opened.
}

function instance(ctx) {
    const entry = instances.get(ctx.instanceId);
    if (!entry) throw new CanvasError("unknown_instance", "Open the Dataforge canvas before invoking its actions.");
    return entry;
}

async function stop(entry) {
    await new Promise((done) => entry.server.close(() => done()));
}

const canvas = createCanvas({
    id: "dataforge",
    displayName: "Dataforge",
    description:
        "Live view of a Dataforge metric build: the business question, the four skills and seven phases, and the proof (results, tests and review).",
    inputSchema: {
        type: "object",
        properties: {
            project: {
                type: "string",
                description: `Path to a Dataforge project folder inside this repository, relative to its root. Defaults to ${DEFAULT_PROJECT}.`,
            },
            view: { type: "string", enum: VIEWS, description: "View to show first." },
        },
        additionalProperties: false,
    },
    actions: [
        {
            name: "show_view",
            description: "Switch the canvas to the question, build or proof view.",
            inputSchema: {
                type: "object",
                properties: { view: { type: "string", enum: VIEWS } },
                required: ["view"],
                additionalProperties: false,
            },
            handler: (ctx) => {
                instance(ctx).state.requestView(ctx.input.view);
                return `Showing the ${ctx.input.view} view.`;
            },
        },
        {
            name: "refresh",
            description: "Re-read the build state, manifest, warehouse copies and GitHub status now.",
            handler: async (ctx) => instance(ctx).state.summary(),
        },
        {
            name: "get_status",
            description: "Summarise what the canvas currently shows: build phase, manifest, changed files and pull request status.",
            handler: async (ctx) => instance(ctx).state.summary(),
        },
    ],
    open: async (ctx) => {
        const project = ctx.input?.project || DEFAULT_PROJECT;
        let entry = instances.get(ctx.instanceId);
        if (!entry || entry.project !== project) {
            if (entry) await stop(entry);
            const state = stateFor(project);
            entry = { ...(await serve(state)), project, state };
            instances.set(ctx.instanceId, entry);
        }
        if (ctx.input?.view) entry.state.requestView(ctx.input.view);
        return { url: entry.url, title: "Dataforge", status: "Live" };
    },
    onClose: async (ctx) => {
        const entry = instances.get(ctx.instanceId);
        if (!entry) return;
        instances.delete(ctx.instanceId);
        await stop(entry);
    },
});

const session = await joinSession({ canvases: [canvas] });

session.on("skill.invoked", (event) => {
    for (const state of states.values()) state.recordSkill(event.data);
});
session.on("tool.execution_start", (event) => {
    for (const state of states.values()) state.recordTool(event.data);
});
