"""Public-repo text is canonical: no em or en dashes, no first- or second-person voice.

Checks Markdown lines added since the merge-base with BASE, commit messages in
BASE..HEAD, a commit message file (commit-msg hook), or stdin (a PR body in CI).
Code spans, fenced code and blockquotes are skipped; quoting a source is allowed.

    python3 tools/check_public_text.py --base origin/main
    python3 tools/check_public_text.py --message-file .git/COMMIT_EDITMSG
    python3 tools/check_public_text.py --stdin < body.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

DASH = re.compile("[\u2013\u2014]")  # en and em dash
PERSON = re.compile(
    r"\b(I(?!/)|I'm|I've|I'll|I'd|us|(?i:me|my|you|your|you're|we|we're|we've|our))\b"
)  # "us" stays lowercase so "US" passes
CODE_SPAN = re.compile(r"`[^`]*`")
INDEX_ROW = re.compile(r"^\| \[[A-Z]+-\d+")  # generated ADR index rows copy older titles
TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by|Reviewed-by|Acked-by|Refs?): ", re.IGNORECASE)


def problems(text: str, where: str) -> list[str]:
    """Each offending line, labelled with where it came from."""
    out: list[str] = []
    fenced = False
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or raw.lstrip().startswith(">") or INDEX_ROW.match(raw):
            continue
        if raw.startswith("#") and where == "commit":
            continue
        line = CODE_SPAN.sub("", raw)
        found = []
        if DASH.search(line):
            found.append("dash")
        who = PERSON.search(line)
        if who:
            found.append(f"person: {who.group(0)!r}")
        if found:
            out.append(f"{where}:{n}: {', '.join(found)}: {raw.strip()[:100]}")
    return out


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


VENDORED = (
    ".claude/skills/speckit-",  # Spec Kit's own text, copied as shipped
    ".specify/",
    "docs/LLM_PRACTICES.md",  # agentic-kit template text, kept identical for copier update
)


def added_markdown(base: str) -> list[str]:
    mb = git("merge-base", base, "HEAD").strip()
    out: list[str] = []
    for path in git("ls-files", "--others", "--exclude-standard", "--", "*.md").split():
        if not path.startswith(VENDORED):  # untracked: every line is new
            with open(path, encoding="utf-8") as f:
                out += problems(f.read(), path)
    for path in git("diff", "--name-only", "--diff-filter=AM", mb, "--", "*.md").split():
        if path.startswith(VENDORED):
            continue
        added = [
            ln[1:]
            for ln in git("diff", "-U0", mb, "--", path).splitlines()
            if ln.startswith("+") and not ln.startswith("+++")
        ]
        out += problems("\n".join(added), path)
    return out


def commit_messages(base: str) -> list[str]:
    out: list[str] = []
    for sha in git("rev-list", f"{base}..HEAD").split():
        body = "\n".join(
            ln for ln in git("log", "-1", "--format=%B", sha).splitlines() if not TRAILER.match(ln)
        )
        out += problems(body, f"commit {sha[:7]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--base", help="ref to compare against: added Markdown lines and commits")
    ap.add_argument("--message-file", help="a commit message file (commit-msg hook)")
    ap.add_argument("--stdin", action="store_true", help="read text, e.g. a PR body, from stdin")
    args = ap.parse_args()
    found: list[str] = []
    if args.base:
        found += added_markdown(args.base) + commit_messages(args.base)
    if args.message_file:
        with open(args.message_file, encoding="utf-8") as f:
            text = "\n".join(ln for ln in f.read().splitlines() if not TRAILER.match(ln))
        found += problems(text, "commit")
    if args.stdin:
        found += problems(sys.stdin.read(), "text")
    for line in found:
        print(line)
    if found:
        print("Public-repo text must be impersonal and use no em or en dashes.")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
