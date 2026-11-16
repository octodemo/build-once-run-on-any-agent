#!/usr/bin/env bash
# Reset the online-marketplace demo to its starting state.
#
#   ./reset.sh          show what would be reset
#   ./reset.sh --yes    reset
#
# Rebuilds the warehouse and removes only what a demo run generates: the
# resolved manifest, forge-builder build state for the Dispatch build, and an
# uncommitted Dispatch entity. It never deletes committed work, never switches
# branches, and never changes anything on GitHub.

set -euo pipefail
cd "$(dirname "$0")"
EXAMPLE="$(pwd)"
REPO="$(git rev-parse --show-toplevel)"
APPLY=false
[ "${1:-}" = "--yes" ] && APPLY=true

say() { printf '%s\n' "$*"; }
act() {
  if $APPLY; then "$@"; else say "  would run: $*"; fi
}

say "Online-marketplace demo reset$($APPLY || printf ' (dry run: add --yes to apply)')"

branch="$(git branch --show-current)"
if [ "$branch" != "main" ]; then
  say "! You are on '$branch'. Switch to main (git switch main) to start from the unbuilt state."
fi

# 1. An uncommitted Dispatch entity left by an interrupted run.
dispatch="marketplace_metric_store/fulfilment/Dispatch"
if [ -d "$dispatch" ]; then
  if git ls-files --error-unmatch "$dispatch" >/dev/null 2>&1; then
    say "! $dispatch is committed on this branch; leaving it alone."
  else
    say "- Remove the uncommitted Dispatch entity"
    act git clean -fdq -- "$dispatch"
  fi
fi

# 2. Uncommitted edits the agent made to tracked files in this example.
changed="$(git diff --name-only -- . | sed "s|^${EXAMPLE#"$REPO"/}/||")"
if [ -n "$changed" ]; then
  say "- Restore files changed during the run:"
  printf '    %s\n' $changed
  act git restore -- $changed
fi

# 3. Generated files in the example folder.
for path in dataforge.manifest.resolved.yaml .build-state .forge; do
  if [ -e "$path" ]; then
    say "- Remove $path"
    act rm -rf -- "$path"
  fi
done

# 4. forge-builder state for Dispatch builds, wherever the skill wrote it.
state_dirs=("$REPO/demos/dataforge/skills/forge-builder/.build-state")
plugins="${COPILOT_HOME:-$HOME/.copilot}/installed-plugins"
if [ -d "$plugins" ]; then
  for dir in "$plugins"/*/*/skills/forge-builder/.build-state; do
    [ -d "$dir" ] && state_dirs+=("$dir")
  done
fi
for dir in "${state_dirs[@]}"; do
  [ -d "$dir" ] || continue
  for file in "$dir"/dispatch--*.json "$dir"/dispatch.lock; do
    if [ -e "$file" ]; then
      say "- Remove build state ${file/#$HOME/~}"
      act rm -f -- "$file"
    fi
  done
done

# 5. A fresh warehouse. This also marks the start of a new run for the canvas.
say "- Rebuild warehouse/east.duckdb and warehouse/west.duckdb"
act python3 seed.py

if $APPLY; then
  say "Done. Issues and pull requests from earlier runs stay on GitHub; the canvas ignores anything created before this reset."
  say "Next: in the Copilot app, ask Copilot to initialize dataforge (DEMO.md, Before you record)."
fi
