# Scripted demo: did we keep our 48-hour promise?

One GitHub issue in, one reviewed pull request out. Dataforge's four skills
run, unchanged, inside the GitHub Copilot app. A canvas beside the chat shows
what is happening. The pull request then gets two independent checks:
human-owned acceptance tests and an advisory Proof Agent review.

The thing worth watching is not that an agent wrote SQL. It is that four
skills with no knowledge of this business produce marketplace-correct code,
because everything they need to know lives in one manifest — and that the
agent asks about the business rules instead of guessing them.

## Before you start

You need the GitHub Copilot app, the GitHub CLI signed in with access to
`octodemo/build-once-run-on-any-agent`, the DuckDB CLI, and Python 3.9+.

Run these from the root of your clone of the repository (the folder that
contains `README.md` and `demos/`):

```bash
brew install duckdb                                   # once, if you don't have it
gh repo set-default octodemo/build-once-run-on-any-agent
cd demos/dataforge/examples/online-marketplace
./reset.sh --yes                                      # builds a fresh warehouse
```

Open the repository as a project in the Copilot app. The repository settings in
`.github/copilot/settings.json` enable Shishir Tewari's Dataforge plugin for
this repository only; it appears under **Customize → Installed** with its four
skills. (To try it without installing anything, use Copilot CLI with
`copilot --plugin-dir demos/dataforge`.)

Then ask Copilot:

> Open the Dataforge canvas.

## Act 1 — The question

**Canvas: The question.** The marketplace promises that every order leaves a
fulfilment centre within 48 hours. There are two regions, each with its own
warehouse: `east` (Sydney) and `west` (Perth).

Walk through Harbour Homewares' seven orders. Two are worth pausing on:

- **105** shipped, but after 68 hours — it still broke the promise, and its
  three dispatch attempts must count as one order.
- **106** was cancelled after its deadline — the promise was already broken.

The rules on screen are the human-owned acceptance tests. The agent is never
pointed at them.

## Act 2 — Cold start

**Canvas: The build.**

> Initialize dataforge for the project in demos/dataforge/examples/online-marketplace.

`forge-init` reads a few lines of seed manifest, then discovers the rest:

| Discovered from | What it learns |
| --- | --- |
| `warehouse/*.duckdb` | two regions, deployed `east` then `west` |
| `information_schema` | the source tables and their columns |
| `marketplace_metric_store/` | one domain (`fulfilment`), one built entity (`Order`) |
| `Schema/*.sql` file names | one grain (`merchant`), two cadences (daily, cumulative) |
| `Code/*.py` | the naming grammar `total_{entity}_{verb}_count` |

The canvas shows `meet` and `miss` in purple: those verbs came from the
manifest, because the business word has to come from somewhere other than the
skills. Scheduling is marked *unsupported*: DuckDB has no scheduler, and the
skill says so instead of inventing one.

## Act 3 — Intake

From the repository root, open the issue:

```bash
gh issue create --title "Track our 48-hour dispatch promise" \
  --body-file demos/dataforge/examples/online-marketplace/issues/dispatch-promise.md \
  --label metric-request
```

> Build the metrics in issue #N.

The issue is vague on purpose. Phase 1 proposes defaults from the manifest and
asks you to confirm the rest. Answer with the agreed rules, in whatever order
it asks:

| If it asks about | Answer |
| --- | --- |
| Grain, cadences, regions | Merchant only; daily and cumulative; both regions. |
| When a promise is met | Dispatched within 48 hours of being placed. Count it on the day it was dispatched. |
| Late dispatches | Still a missed promise. Count it on the day the 48 hours ran out. |
| Cancellations | Cancelled before the deadline: don't count it. Cancelled after the deadline: it already missed. |
| Retries | One order is one promise, however many dispatch attempts it took. |
| Deleted rows | Exclude them — they are test orders. |

Each answer is a checkpoint. The canvas shows the phase waiting for a person.

## Act 4 — Discovery, design and code

Phases 2 to 5. Every query goes through `forge-dbx`, which refuses row-level
`SELECT *` even against synthetic data on a laptop. `forge-lint` names the
metrics: `total_dispatch_meet_count` and `total_dispatch_miss_count`.

Watch the join decision: `dispatch_attempts` has several rows for some orders,
so it has to be reduced to one row per order before it meets `orders`.

The new `Dispatch/` files appear in the canvas. The runners only print SQL;
nothing touches a warehouse until `forge-dbx` runs it:

```bash
python3 marketplace_metric_store/common/daily_runner.py \
  marketplace_metric_store/fulfilment/Dispatch/Code/Dispatch_Metrics_Snapshot_Daily.py
```

## Act 5 — Tests, approval and deployment

Phase 6 writes and runs the agent's own tests. Phase 7 prints the table
definitions and **stops until you approve** — say yes on stage; that pause is
the point. Then it deploys to `east`, and only after that succeeds, to `west`,
and loads the last 30 days.

**Canvas: The proof.** Harbour Homewares' numbers line up with the agreed rules
(1 met; 2 missed on day 3, 1 on day 4), and each region shows promises met and
missed by merchant.

## Act 6 — Someone else checks the work

The pull request triggers two checks:

| Check | What it is | Role |
| --- | --- | --- |
| **Dispatch promise acceptance tests** | Human-owned tests in `acceptance/`; expected values computed independently from the source data | Required to merge |
| **Proof Agent review** | Andrea Griffiths' verifier skill, run by GitHub Actions through the Copilot SDK; it reviews the diff, not the agent's own account of it | Advisory |

Proof Agent's verdict is whatever it says on the day: PASS, FAIL or PARTIAL.
Read it out as it is. A person decides whether to merge.

In the rehearsal run, [pull request #4](https://github.com/octodemo/build-once-run-on-any-agent/pull/4),
the acceptance tests passed in both regions, and Proof Agent returned **FAIL**:
it flagged that the pipelines insert the runner's date and catalog names into
SQL with f-strings. That is a fair point and a judgement call at the same
time: the values come from the team's own runner, not from users, and the
existing Order pipelines use the same pattern. A reasonable decision is to
merge and raise a follow-up to validate `SNAPSHOT_DATE` in the shared runner.
That is the point of the slide: the tests prove the rules, the AI reviewer
raises concerns, and a person weighs them.

Dataforge also manages the issue: once the pull request is open, it comments on
the issue and may close it as delivered.

## The closing point

- The four skills are the same files Shishir ships for Claude Code and Cursor,
  loaded unchanged into GitHub Copilot.
- Everything this business needs is in one manifest. The skills never mention
  merchants, Sydney or dispatch.
- The canvas is the Copilot-app part. The skills don't know it exists.

## If something goes wrong

| Symptom | What to do |
| --- | --- |
| No `forge-*` skills | Check **Customize → Installed** for Dataforge, or start a new session. |
| Dataforge doesn't stop to ask | Answer anyway: when it lists its assumptions, confirm or correct them from the table in Act 3. |
| DuckDB says a file is locked | Close any other `duckdb` session on that warehouse. |
| Proof Agent posts a timeout | Version 1.1.2 waits a fixed 60 seconds for the review; the workflow uses a fast model to fit. Re-run the job, or show the reference pull request. |
| Proof Agent posts an authorisation error | The organisation must allow Copilot requests from Actions. Show the reference pull request instead. |
| Running out of time | Switch to the recording or [pull request #4](https://github.com/octodemo/build-once-run-on-any-agent/pull/4), the completed rehearsal run. |

## Reset

```bash
./reset.sh          # shows what it would do
./reset.sh --yes    # does it
```

It rebuilds the warehouse and removes only what a run generates. Issues and
pull requests from earlier runs stay on GitHub; the canvas ignores anything
older than the reset.
