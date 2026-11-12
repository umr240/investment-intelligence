#!/bin/sh
# Installs the pinned Spec Kit files that .gitignore leaves out (the /speckit-*
# skills, scripts and templates). Run once per clone. Spec Kit keeps the
# tracked constitution, extensions.yml and template overrides; the check below
# fails if it ever stops doing so.
set -eu
cd "$(git rev-parse --show-toplevel)"
uvx --from git+https://github.com/github/spec-kit.git@v1.2.5 \
  specify init --here --integration claude --script sh --force --non-interactive
git diff --quiet -- .specify .claude/skills || {
  echo "setup_speckit: Spec Kit changed tracked files; review with git diff" >&2
  exit 1
}
