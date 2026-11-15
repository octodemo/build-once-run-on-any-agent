# Copilot instructions for this repository

This repository holds the materials for the talk *Build once, run on any agent*
and one runnable demo.

- The Dataforge demo project is `demos/dataforge/examples/online-marketplace/`.
  Run the Dataforge skills against that project. Its seed manifest is
  `dataforge.manifest.yaml` in that folder, and the resolved manifest belongs
  next to it. The template under `demos/dataforge/assets/` is not this
  project's manifest.
- Issues and pull requests for the demo belong in
  `octodemo/build-once-run-on-any-agent`, never the upstream repository this
  fork came from.
- Do not modify files under `acceptance/`; they are human-owned checks.
- When a script parses DuckDB output, request an explicit format such as
  `-json` or `-csv`.
