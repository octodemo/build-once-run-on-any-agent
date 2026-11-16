# Dataforge canvas

A side panel for the GitHub Copilot app that shows a Dataforge build as it
happens, next to the chat. Ask Copilot: **"Open the Dataforge canvas."**

| View | What it shows | Where it comes from |
| --- | --- | --- |
| **The question** | The GitHub issue, the 48-hour promise, the story orders and the agreed rules | The issue file, the GitHub issue, `acceptance/online-marketplace/story.json` |
| **The build** | The Dataforge diagram from the slide (issue → four skills → pull request, the manifest, the data platform, you), lit up as the agent works: the skill in use, the region being queried, the step it's on, and when it's waiting for you. A one-line "now" banner says the same in plain English. | Copilot session events (skills, tool calls, questions, approvals), forge-builder's build-state file, `dataforge.manifest.resolved.yaml`, `git` |
| **The proof** | Story orders, expected versus the pipeline; met and missed promises by merchant in each region; the pull request's checks and the Proof Agent verdict | A private copy of each DuckDB warehouse, `gh` |

## Ground rules

- **Read-only.** It never writes to the project. It reads a *copy* of each
  warehouse, so it never holds a lock the agent needs.
- **Nothing simulated.** Empty states say what hasn't happened yet. Anything
  older than the last `python seed.py` (a rehearsal's build state, issue or pull
  request) is ignored.
- **Host-specific on purpose.** The Dataforge skills are unchanged and don't
  know this canvas exists. The skills are the portable procedure; the canvas is
  the part that belongs to this host, the Copilot app.

Agent-callable actions: `show_view` (question, build or proof), `refresh`, and
`get_status`.

## Files

| File | Purpose |
| --- | --- |
| `extension.mjs` | Registers the canvas with the Copilot app and listens for skill and tool events |
| `state.mjs` | Builds the canvas state from real artifacts |
| `server.mjs` | Loopback-only HTTP server for the page and its state |
| `ui.html` | The page, using the app's theme tokens |
| `preview.mjs` | Serves the canvas outside Copilot: `node .github/extensions/dataforge-canvas/preview.mjs` |

Requires Node.js, the DuckDB CLI and the GitHub CLI. The manifest summary uses
the Ruby that ships with macOS to read YAML; without it, the canvas shows the
manifest as text.
