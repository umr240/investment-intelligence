#!/bin/sh
# Installs the Spec Kit files that .gitignore leaves out (the /speckit-*
# skills, scripts and templates). Run once per clone. v1.2.5 is pinned by
# commit, its dependencies are resolved as of --exclude-newer, the installed
# files must match tools/speckit.sha256, and no tracked file may change.
set -eu
cd "$(git rev-parse --show-toplevel)"
state() { { git diff HEAD; git status --porcelain; } | git hash-object --stdin; }
before=$(state)
uvx --exclude-newer 2026-11-01 \
  --from "git+https://github.com/github/spec-kit.git@4572a67fe0e72a6837e2d7bb0fda875bc41482e5" \
  specify init --here --integration claude --script sh --force --non-interactive
[ "$(state)" = "$before" ] || {
  echo "setup_speckit: Spec Kit changed tracked files; review with git status" >&2
  exit 1
}
shasum -a 256 --quiet -c tools/speckit.sha256 || {
  echo "setup_speckit: installed files differ from tools/speckit.sha256" >&2
  exit 1
}
