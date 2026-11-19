# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""May the agent merge this PR now? Exit 0 only if every condition holds.

    uv run tools/gate/merge_ready.py --pr 12 --workdir .e2e/gate-7

Conditions: gate.toml grants the agent merge authority; the gate's last run in --workdir
was full (static + live; static alone only if `[merge] require_live = false` is set on the
base branch as well as this one, and then a YES says so), on a clean tree, at the PR's head commit, and fully green; the
latest PR comment headed `## pr-verifier` by the PR's author says NOT BLOCKING for the PR's
head commit (SHA on its second line) and was posted after that commit; its findings follow the
tagged format and every tag is in `[merge] merge_on` read from the base branch (agentic-kit ADR 004); the
PR is open, not a
draft, targets the gate's base branch, is mergeable, changes no `specs/*/spec.md` (the
owner's merge is a spec's approval, agentic-kit ADR 005), and every CI check has completed
successfully. On YES it prints the merge command, whose `--match-head-commit` stops anything
pushed after this check from riding along. Standard library + the `gh` CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("needs Python 3.11+: run it with `uv run tools/gate/merge_ready.py`")
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OK_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
VERIFIER_HEADING = "## pr-verifier"


def gh_pr(pr: str) -> dict[str, Any]:
    fields = (
        "number,state,isDraft,mergeable,mergeStateStatus,baseRefName,headRefOid,"
        "statusCheckRollup,comments,commits,author,files,title"
    )
    p = subprocess.run(
        ["gh", "pr", "view", pr, "--json", fields],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        raise SystemExit(f"[FAIL] gh pr view {pr}: {p.stderr.strip()}")
    data: dict[str, Any] = json.loads(p.stdout)
    return data


def check_states(rollup: list[dict[str, Any]]) -> list[str]:
    """Names of checks that are not finished-and-green (CheckRun and StatusContext shapes)."""
    bad = []
    for c in rollup:
        if c.get("__typename") == "StatusContext" or "state" in c:
            if c.get("state") != "SUCCESS":
                bad.append(f"{c.get('context')}={c.get('state')}")
        elif (
            c.get("status") != "COMPLETED" or c.get("conclusion") not in OK_CONCLUSIONS
        ):
            bad.append(f"{c.get('name')}={c.get('conclusion') or c.get('status')}")
    return bad


def base_merge_config(base: str) -> dict[str, Any] | None:
    """`[merge]` from gate.toml on origin/<base>, fetched now, or None if it can't be read.

    Settings that loosen a check (the live waiver, `merge_on`) count only from the base, so
    a PR cannot grant them to itself or outlive their removal.
    """
    for cmd in (["fetch", "-q", "origin", base], ["show", "FETCH_HEAD:gate.toml"]):
        p = subprocess.run(
            ["git", *cmd], cwd=ROOT, capture_output=True, text=True, check=False
        )
        if p.returncode != 0:
            return None
    try:
        merge: dict[str, Any] = tomllib.loads(p.stdout).get("merge", {})
        return merge
    except tomllib.TOMLDecodeError:
        return None


# A fence opens or closes at up to 3 spaces (CommonMark). Only a column-0 fence is allowed;
# an indented one is still tracked, so it can't hide what follows, and is a problem.
FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})")
HEADING = re.compile(r"^#{1,6}\s")
# A finding: a list item at column 0 (`1.`, `1)`, `-`, `*` or `+`, then spaces or the end).
ITEM = re.compile(r"^(\d+[.)]|[-*+])( +|$)")
# A list marker indented 1 to 3 spaces, or any tab: Markdown could read it either as a
# finding or as detail, so the format forbids it and merge_ready says NO.
AMBIGUOUS = re.compile(
    r"^ {1,3}(\d+[.)]|[-*+])(\s|$)|^\s*\t|^(\d+[.)]|[-*+])\t|^ {0,3}>|^ {0,3}<|^ {4,}(```|~~~)"
)
TAG = re.compile(r"^\*{0,2}\[([a-z0-9-]+)\]")
# Outside the section: a list line led by any bracket, valid tag or not, but not a link,
# at any indent and inside blockquotes.
LOOKS_TAGGED = re.compile(r"^[\s>]*(\d+[.)]|[-*+])\s*\*{0,2}\[[^\]]*\](?!\()")
SUMMARY = re.compile(r"^tags:\s*total=(\d+)((?:\s+[a-z0-9-]+=\d+)*)\s*$")


def findings(body: str) -> tuple[list[str], list[str]]:
    """(problems, tags) for a verifier report in agentic-kit ADR 004's format.

    The first non-empty line after the verdict is `tags: total=N tag=k ...`. Every report
    has a heading starting `### Findings`; its section runs to the next heading. In it,
    each list item at column 0 is one finding and starts with `[tag]`; detail is indented
    4 or more spaces. A list line indented 1 to 3 spaces, or a tab, is a problem, because
    Markdown could render it either way. A line elsewhere that starts like a tagged
    finding is a problem. Code fences at column 0 are skipped; an indented fence, a quote
    (`>`) or HTML (`<`) in the section is a problem.
    """
    lines: list[str] = []
    opener = ""  # the open fence's run (e.g. ```` or ~~~); a closer repeats it, at least as long
    indented_fences = 0
    for ln in body.splitlines():
        f = FENCE.match(ln)
        if f and (not opener or (f.group(2)[0] == opener[0] and len(f.group(2)) >= len(opener) and not ln[f.end():].strip())):
            if f.group(1):
                indented_fences += 1  # rendered as a fence, so tracked, but not allowed
            opener = "" if opener else f.group(2)
            lines.append("")
            continue
        lines.append("" if opener else ln)
    fenced = bool(opener)
    problems: list[str] = []
    if fenced:
        problems.append("a code fence is never closed, so the rest of the report is unreadable")
    if indented_fences:
        problems.append("an indented code fence: put code in a fence at column 0")
    text = [ln.strip() for ln in lines[1:] if ln.strip()]  # line 0 is the heading
    summary = SUMMARY.match(text[1]) if len(text) > 1 else None
    if summary is None:
        problems.append("no `tags: total=N` line after the verdict")
    start = next((i for i, ln in enumerate(lines) if ln.startswith("### Findings")), None)
    if start is None:
        problems.append("no `### Findings` heading")
    items: list[str | None] = []
    outside: list[str] = []
    ambiguous: list[str] = []
    in_section = False
    for i, ln in enumerate(lines):
        if i == start:
            in_section = True
            continue
        if in_section and HEADING.match(ln):
            in_section = False
        if in_section and AMBIGUOUS.match(ln):
            ambiguous.append(ln.strip()[:40])
        elif in_section and (item := ITEM.match(ln)):
            tagged = TAG.match(ln[item.end():])
            items.append(tagged.group(1) if tagged else None)
        elif not in_section and LOOKS_TAGGED.match(ln):
            outside.append(ln.strip()[:40])
    tags = [t for t in items if t]
    if len(tags) < len(items):
        problems.append(f"{len(items) - len(tags)} finding(s) without a [tag]")
    if outside:
        problems.append(f"tagged line outside ### Findings: {outside[0]!r}")
    if ambiguous:
        problems.append(
            f"list line indented 1-3 spaces or with a tab in ### Findings: {ambiguous[0]!r} "
            "(findings start at column 0; detail is indented 4 spaces)"
        )
    if summary is not None:
        total = int(summary.group(1))
        if total != len(items):
            problems.append(f"tags: total={total} but {len(items)} finding(s)")
        declared = dict(kv.split("=") for kv in summary.group(2).split())
        counted = {t: str(tags.count(t)) for t in set(tags)}
        if declared != counted:
            problems.append(f"tag counts {declared} vs findings {counted}")
    return problems, tags


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pr", required=True)
    ap.add_argument(
        "--workdir", type=Path, required=True, help="the gate run to rely on"
    )
    ap.add_argument("--config", type=Path, default=ROOT / "gate.toml")
    args = ap.parse_args()

    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    workdir = args.workdir if args.workdir.is_absolute() else ROOT / args.workdir
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)

    merge = cfg.get("merge", {})
    base = cfg.get("base", "main").split("/")[-1]
    base_merge = base_merge_config(base)
    allowed = bool(merge.get("agent_may_merge", False))
    record(
        "authority: gate.toml [merge] agent_may_merge", allowed, str(allowed).lower()
    )

    pr = gh_pr(args.pr)
    run_file = workdir / "run.json"
    run: dict[str, Any] = json.loads(run_file.read_text()) if run_file.exists() else {}
    record(
        "gate: run recorded",
        bool(run),
        str(run_file.relative_to(ROOT)) if run else "no run.json",
    )
    live_waived = False
    if run:
        wants_waiver = merge.get("require_live", True) is False
        live_waived = (
            wants_waiver
            and not run.get("live")
            and (base_merge or {}).get("require_live", True) is False
        )
        if live_waived:
            record(
                "gate: static run (live gate waived in gate.toml)",
                bool(run.get("static")),
                "",
            )
        else:
            record(
                "gate: full run (static + live)",
                bool(run.get("static") and run.get("live")),
                f"waiver not on origin/{base}" if wants_waiver and not run.get("live") else "",
            )
        record(
            "gate: clean tree",
            not run.get("dirty"),
            "dirty" if run.get("dirty") else "clean",
        )
        record(
            "gate: at the PR head",
            run.get("head") == pr["headRefOid"],
            f"gate {str(run.get('head'))[:10]} vs PR {pr['headRefOid'][:10]}",
        )
        record(
            "gate: all passed",
            run.get("total", 0) > 0 and run.get("passed") == run.get("total"),
            f"{run.get('passed')}/{run.get('total')}",
        )

    # Only the PR author's account (the session that ran the verifier) may post the verdict:
    # on a public repo anyone else can comment.
    pr_author = (pr.get("author") or {}).get("login", "")
    reviews = [
        c
        for c in pr.get("comments") or []
        if c.get("body", "").lstrip().startswith(VERIFIER_HEADING)
        and (c.get("author") or {}).get("login") == pr_author
        and pr_author
    ]
    latest = max(reviews, key=lambda c: c["createdAt"]) if reviews else None
    head_time = max((c["committedDate"] for c in pr.get("commits") or []), default="")
    if latest is None:
        record(
            "verifier: NOT BLOCKING on the PR",
            False,
            f"no comment headed '{VERIFIER_HEADING}'",
        )
    else:
        verdict = next(
            (ln.strip() for ln in latest["body"].splitlines()[1:] if ln.strip()), ""
        )
        record(
            "verifier: NOT BLOCKING on the PR",
            verdict.upper().startswith("NOT BLOCKING"),
            verdict[:80],
        )
        words = verdict.split()
        reviewed = (
            words[2]
            if verdict.upper().startswith("NOT BLOCKING") and len(words) > 2
            else ""
        )
        record(
            "verifier: reviewed the head commit",
            reviewed == pr["headRefOid"],
            f"review of {reviewed[:10] or '?'} vs PR head {pr['headRefOid'][:10]}",
        )
        record(
            "verifier: review posted after the head commit",
            latest["createdAt"] > head_time,
            f"review {latest['createdAt']} vs head commit {head_time}",
        )
        problems, tags = findings(latest["body"])
        record(
            "verifier: findings tagged (agentic-kit ADR 004 format)",
            not problems,
            "; ".join(problems) or f"{len(tags)} finding(s)",
        )
        raw = (base_merge or {}).get("merge_on", [])
        typed = isinstance(raw, list) and all(isinstance(t, str) for t in raw)
        merge_on = list(raw) if typed else []
        record(
            f"tags: merge_on on origin/{base} is valid",
            typed and "owner" not in merge_on,
            f"must be a list of tag strings, got {raw!r}"
            if not typed
            else "`owner` in merge_on would let every finding through"
            if "owner" in merge_on
            else (", ".join(merge_on) or "empty: every finding goes to the owner"),
        )
        held = sorted({t for t in tags if t not in merge_on})
        record(
            "verifier: every finding may merge (merge_on)",
            not held,
            f"owner merges: {', '.join(f'[{t}] x{tags.count(t)}' for t in held)}"
            if held
            else f"{len(tags)} finding(s), all in merge_on",
        )

    record(
        "PR: open, not draft",
        pr["state"] == "OPEN" and not pr["isDraft"],
        f"{pr['state']}, draft={pr['isDraft']}",
    )
    record(
        "PR: targets the gate base",
        pr["baseRefName"] == base,
        f"{pr['baseRefName']} (gate base {base})",
    )
    record(
        "PR: mergeable",
        pr["mergeable"] == "MERGEABLE",
        f"{pr['mergeable']} / {pr['mergeStateStatus']}",
    )
    specs = [
        f.get("path", "")
        for f in pr.get("files") or []
        if re.match(r"^specs/[^/]+/spec\.md$", f.get("path", ""))
    ]
    nfiles = len(pr.get("files") or [])
    record(
        "PR: changes no spec (the owner approves a spec by merging it)",
        not specs and nfiles < 100,
        f"owner merges: {', '.join(specs)}"
        if specs
        else f"{nfiles} files: gh lists at most 100, so the owner merges"
        if nfiles >= 100
        else "no spec.md changed",
    )
    rollup = pr.get("statusCheckRollup") or []
    bad = check_states(rollup)
    record("CI: checks present", bool(rollup), f"{len(rollup)} checks")
    record("CI: all green", bool(rollup) and not bad, ", ".join(bad[:5]) or "green")

    failed = [n for n, ok, _ in results if not ok]
    print(
        f"\nmerge-ready: {('YES (live waived)' if live_waived else 'YES') if not failed else 'NO'}"
        + (f" — {failed}" if failed else f" (head {pr['headRefOid']})")
    )
    if failed:
        return 1
    command = f"gh pr merge {args.pr} --squash --match-head-commit {pr['headRefOid']}"
    if pr.get("title"):  # the squash commit, and so the changelog line, is the checked PR title
        command += f" --subject {shlex.quote(str(pr['title']) + ' (#' + str(pr.get('number', args.pr)) + ')')}"
    # From the base, like merge_on: a PR must not choose whose name its own merge carries.
    author = (base_merge or {}).get("author_email")
    if author:
        command += f" --author-email {shlex.quote(str(author))}"
    print(f"merge with: {command}")
    if run.get("live") is not True:
        print("live gate waived: say so in the merge body and run it when it is owed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
