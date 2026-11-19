"""Public-repo text is canonical: no em or en dashes, no first- or second-person voice,
no co-author trailer or AI-tool footer (the git author is the only author).
Squash merges take their message from the branch's commits, so --base covers them;
CI checks the PR title with the body. A hand-typed `gh pr merge --body` is not checked.

Checks Markdown lines added since the merge-base with BASE, commit messages in
BASE..HEAD, a commit message file (commit-msg hook), or stdin (a PR body in CI).
Code spans, fenced code and blockquotes are skipped, so a source can be quoted;
attribution is checked inside fences and blockquotes too, and only a code span quotes it.

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
# One author of record, the git author: no co-author trailer at all, and no AI-tool footer.
AI_TOOL = r"(claude|anthropic|copilot|codex|chatgpt|openai|cursor|gemini|aider|devin)"
FOOTER = (  # a whole line crediting a tool, e.g. "Generated with [Claude Code](url)"
    r"^\W*(generated|written|created|made|built|assisted) (with|by|using) "
    rf"\[?(\w+ )?{AI_TOOL}( \w+)?\]?(\(\S*\))?\W*$"
)
ATTRIBUTION = re.compile(
    r"^\s*co-authored-by:|noreply@anthropic\.com"
    rf"|^\s*[\w-]+-by:.*\b{AI_TOOL}\b|{FOOTER}"
    r"|\b(generated|written|created) (with|by) claude code\b",
    re.IGNORECASE,
)


def flags_attribution(raw: str) -> bool:
    """Checked inside a fence or quote too, so neither hides a trailer; code spans quote."""
    return bool(ATTRIBUTION.search(CODE_SPAN.sub("", raw)))


def without_trailers(text: str) -> str:
    """Drop trailer lines, except attribution, which is checked."""
    return "\n".join(
        ln for ln in text.splitlines() if not TRAILER.match(ln) or ATTRIBUTION.search(ln)
    )


def problems(text: str, where: str) -> list[str]:
    """Each offending line, labelled with where it came from."""
    out: list[str] = []
    fenced = False
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or raw.lstrip().startswith(">") or INDEX_ROW.match(raw):
            if flags_attribution(raw.lstrip("> ")):
                out.append(f"{where}:{n}: attribution: {raw.strip()[:100]}")
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
        if ATTRIBUTION.search(line):
            found.append("attribution")
        if found:
            out.append(f"{where}:{n}: {', '.join(found)}: {raw.strip()[:100]}")
    return out


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


VENDORED = (
    # agentic-kit template text (the speckit-* skills, the spec template
    # override, the ratified constitution), kept identical for copier update;
    # Spec Kit's own copies are gitignored
    ".claude/skills/speckit-",
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
        out += problems(without_trailers(git("log", "-1", "--format=%B", sha)), f"commit {sha[:7]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--base", help="ref to compare against: added Markdown lines and commits")
    ap.add_argument("--message-file", help="a commit message file (commit-msg hook)")
    ap.add_argument("--stdin", action="store_true", help="read text, e.g. a PR body, from stdin")
    args = ap.parse_args()
    for stream in (sys.stdin, sys.stdout):  # Windows consoles default to cp1252
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    found: list[str] = []
    if args.base:
        found += added_markdown(args.base) + commit_messages(args.base)
    if args.message_file:
        with open(args.message_file, encoding="utf-8") as f:
            found += problems(without_trailers(f.read()), "commit")
    if args.stdin:
        found += problems(sys.stdin.read(), "text")
    for line in found:
        print(line)
    if found:
        print(
            "Public-repo text must be impersonal, use no em or en dashes, and carry no co-author"
            " trailer or AI-tool attribution: the git author is the only author."
        )
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
