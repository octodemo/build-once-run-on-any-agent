// Serve the Dataforge canvas outside a Copilot session, to check it in a
// browser. Skill activity only appears inside a Copilot session.
//
//   node .github/extensions/dataforge-canvas/preview.mjs [port] [project]

import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { serve } from "./server.mjs";
import { createState } from "./state.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(HERE, "..", "..", "..");
const port = Number(process.argv[2] || 4319);
const exampleDir = resolve(repoRoot, process.argv[3] || "demos/dataforge/examples/online-marketplace");

const { url } = await serve(createState({ repoRoot, exampleDir }), port);
process.stdout.write(`Dataforge canvas preview: ${url}\n`);
