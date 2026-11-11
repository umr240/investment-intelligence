# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""End-to-end gate: nothing is committed until this passes.

Reads `gate.toml` at the repo root. Static checks compare the working tree with
the merge-base of `base` (scope, secrets, machine paths, forbidden files, lock
files, LLM boundary, decision log, finding baselines). Live checks run each
variant's commands against scratch copies, with services started first; every
`[guard]` file must be byte-identical afterwards.

    uv run tools/gate/gate.py --workdir .e2e/gate-1
    uv run tools/gate/gate.py --workdir .e2e/ci --static-only --base origin/main

Every check prints one `[PASS]` / `[FAIL]` line; the log and results.json land
in the workdir. Exit code 0 means every check passed. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("needs Python 3.11+: run it with `uv run tools/gate/gate.py`")
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

SECRET = (
    r"sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|xox[abpr]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|[a-z+]+://[^\s:/@]+:[^\s@/]{3,}@"
    r"|(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"
)
MACHINE_PATH = r"/Users/[a-z]|/home/[a-z]|[A-Z]:\\Users\\"
FORBIDDEN = r"(^|/)\.env$|\.(db|sqlite3?)$|\.db-(wal|shm)$"
PROVIDERS = [
    "anthropic",
    "claude_agent_sdk",
    "openai",
    "google.genai",
    "google.generativeai",
    "mistralai",
    "cohere",
    "litellm",
    "langchain_anthropic",
    "langchain_openai",
    "langchain",
    "langchain_community",
    "llama_index",
    "lightrag",
    "@anthropic-ai/sdk",
    "@anthropic-ai/claude-agent-sdk",
    "@google/genai",
    "@google/generative-ai",
    "@mistralai/mistralai",
    "cohere-ai",
    "@ai-sdk/anthropic",
    "@ai-sdk/google",
    "@ai-sdk/openai",
    "@langchain/anthropic",
    "@langchain/openai",
    "@langchain/community",
    "llamaindex",
]
# `from google import genai` names the package only after `import`.
GOOGLE_FROM_IMPORT = re.compile(
    r"^\s*from\s+google\s+import\s+[^\n#]*\b(genai|generativeai)\b", re.MULTILINE
)
SOURCE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".e2e"}


@dataclass
class Check:
    group: str
    name: str
    ok: bool
    detail: str = ""


RESULTS: list[Check] = []


def record(group: str, name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append(Check(group, name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {group:8} {name}: {detail}", flush=True)
    return ok


def base_env() -> dict[str, str]:
    """os.environ minus a VIRTUAL_ENV that belongs to another checkout (uv warns, tools misfire)."""
    env = dict(os.environ)
    venv = env.get("VIRTUAL_ENV")
    if venv and not Path(venv).resolve().is_relative_to(ROOT):
        del env["VIRTUAL_ENV"]
    return env


def sh(
    cmd: str, cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: int = 1800
) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            env={**base_env(), **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    return p.returncode, p.stdout + p.stderr


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout


def last_line(out: str) -> str:
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    return lines[-1][:160] if lines else ""


def fill(text: str, values: dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def digest(path: Path) -> str:
    """File plus any SQLite -wal: committed pages can sit there until a checkpoint.
    A directory covers every file's relative path and contents."""
    if not path.exists():
        return "absent"
    if path.is_dir():
        h = hashlib.sha256()
        # Opening a SQLite file read-only can create -shm and an empty -wal.
        files = (
            p
            for p in path.rglob("*")
            if p.is_file()
            and not p.name.endswith("-shm")
            and not (p.name.endswith("-wal") and p.stat().st_size == 0)
        )
        for f in sorted(files):
            h.update(f.relative_to(path).as_posix().encode() + b"\0")
            h.update(hashlib.sha256(f.read_bytes()).digest())
        return h.hexdigest()
    h = hashlib.sha256(path.read_bytes())
    wal = path.with_name(path.name + "-wal")
    if wal.exists():
        h.update(wal.read_bytes())
    return h.hexdigest()


def snapshot(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix in (".db", ".sqlite", ".sqlite3"):
        s, d = sqlite3.connect(f"file:{src}?mode=ro", uri=True), sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            s.close()
            d.close()
    elif src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


# ── static ──────────────────────────────────────────────────────────────────


def changed_files(base: str) -> tuple[list[list[str]], list[str], str]:
    """(status, path) rows and added lines since the merge-base, untracked files included."""
    mb = git("merge-base", base, "HEAD").strip()
    rows = [
        ln.split("\t")
        for ln in git("diff", "--name-status", mb).splitlines()
        if ln.strip()
    ]
    untracked = [
        f for f in git("ls-files", "--others", "--exclude-standard").splitlines() if f
    ]
    rows += [["A", f] for f in untracked]
    added = [
        ln[1:]
        for ln in git("diff", "-U0", mb).splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    ]
    for f in untracked:
        p = ROOT / f
        if p.is_file() and p.stat().st_size < 2_000_000:
            added += p.read_text(encoding="utf-8", errors="replace").splitlines()
    return rows, added, mb


def provider_imports(text: str, providers: list[str]) -> list[str]:
    names = "|".join(re.escape(p) for p in providers)
    py = re.compile(rf"^\s*(?:import|from)\s+({names})(?:[\s.]|$)", re.MULTILINE)
    js = re.compile(
        rf"""(?:from\s+|require\(\s*|import\(\s*)['"]({names})(?:/[^'"]*)?['"]"""
    )
    found = [m.group(1) for m in py.finditer(text)]
    found += [m.group(1) for m in js.finditer(text)]
    found += [
        f"google.{m.group(1)}"
        for m in GOOGLE_FROM_IMPORT.finditer(text)
        if f"google.{m.group(1)}" in providers
    ]
    return found


def llm_boundary(cfg: dict[str, Any]) -> None:
    allowed = set(cfg.get("allowed", []))
    providers = [*cfg.get("providers", PROVIDERS), *cfg.get("extra_providers", [])]
    skip = set(cfg.get("skip_dirs", ["tests"])) | SKIP_DIRS
    files = git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    found = set()
    for rel in files:
        parts = rel.split("/")
        if not rel.endswith(SOURCE_EXT) or any(
            p in skip or p.startswith(".") for p in parts[:-1]
        ):
            continue
        p = ROOT / rel
        if p.is_file() and provider_imports(
            p.read_text(encoding="utf-8", errors="replace"), providers
        ):
            found.add(rel)
    stray, missing = sorted(found - allowed), sorted(allowed - found)
    record(
        "static",
        "LLM boundary: allow-listed call sites only",
        not stray and not missing,  # a missing site means the scan itself went blind
        f"stray: {stray}; not found: {missing}"
        if stray or missing
        else (", ".join(sorted(found)) or "no provider imports"),
    )


def decision_log(path: Path) -> None:
    if not path.exists():
        record("static", "decision log", False, f"{path.relative_to(ROOT)} missing")
        return
    text = path.read_text(encoding="utf-8")
    ids = re.findall(r"^## (DEC-\d+)\b", text, re.MULTILINE)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    record(
        "static",
        "decision log: ids unique",
        not dupes,
        f"dupes: {dupes}" if dupes else f"{len(ids)} entries",
    )
    refs: set[str] = set()
    for f in git("ls-files", "--cached", "--others", "--exclude-standard").splitlines():
        p = ROOT / f
        if p.suffix in (".md", *SOURCE_EXT, ".toml", ".yml", ".yaml") and p.is_file():
            refs |= set(
                re.findall(
                    r"\bDEC-\d+\b", p.read_text(encoding="utf-8", errors="replace")
                )
            )
    dangling = sorted(refs - set(ids))
    record(
        "static",
        "decision log: references resolve",
        not dangling,
        f"dangling: {dangling[:5]}" if dangling else "clean",
    )


ADR_STATUS = ("proposed", "accepted", "deferred", "superseded", "rejected", "deprecated", "draft")
# `**Status**: x`, `**Status:** x`, `**Status:** **X**`, `Status: x`, front matter
# `status: "x"`, MADR's `## Status` heading with the value on a following line,
# a metadata table row `| **Status** | x |`, or any of these in a blockquote.
STATUS_LINE = re.compile(
    r"^\s*>?\s*[-*]?\s*\*{0,2}status\*{0,2}\s*:[\s*_\"']*([A-Za-z]+)"
    r"|^#{1,6}\s*status\s*\n+[\s*_-]*([A-Za-z]+)"
    r"|^\|\s*\*{0,2}status\*{0,2}\s*\|[\s*_\"']*([A-Za-z]+)",  # table row: | **Status** | x |
    re.IGNORECASE | re.MULTILINE,
)
# A backticked `path:line`, `path:12-30` or `path:12,40`.
CITATION = re.compile(r"`([\w./-]+\.[\w.]+):(\d+(?:[-,]\d+)*)`")
# Without a `/`, only these count as files, so `db.internal:5432` is a host, not a citation.
FILE_EXT = {
    *(e.lstrip(".") for e in SOURCE_EXT),
    "md", "toml", "yml", "yaml", "json", "jinja", "sh", "txt", "sql", "cfg", "ini",
    "go", "rs", "java", "kt", "rb", "php", "cs", "c", "h", "cpp", "hpp", "swift",
    "css", "scss", "html", "vue", "svelte", "lock", "env",
}


INDEX_START, INDEX_END = "<!-- adr-index:start -->", "<!-- adr-index:end -->"


def adr_index_table(adr_dir: Path, index: Path, prefix: str = "ADR") -> str:
    """The ADR table, generated from the ADR files (agentic-kit ADR 005): never hand-kept."""
    rows = ["| ADR | Title | Status | Date |", "|---|---|---|---|"]
    p_ = re.escape(prefix)
    name = re.compile(rf"^({p_}-\d+(?:-A\d+)?)(?:[-.].*)?\.md$")
    for p in sorted(adr_dir.glob(f"{prefix}-*.md")):
        m = name.match(p.name)
        if not m:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        h = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = re.sub(rf"^{p_}-\d+(?:-A\d+)?\s*[:\u2014-]\s*", "", h.group(1).strip()) if h else p.stem
        st = STATUS_LINE.search(text)
        status = (st.group(1) or st.group(2) or st.group(3)).lower() if st else "?"
        d = re.search(r"^[\s>*-]*\**date\**\s*:\**\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE | re.MULTILINE)
        rel = os.path.relpath(p, index.parent)
        rows.append(f"| [{m.group(1)}]({rel}) | {title.replace('|', '/')} | {status} | {d.group(1) if d else ''} |")
    return "\n".join(rows)


def index_section(text: str) -> str | None:
    """The table between the markers, or None unless both are present, start first."""
    start = text.find(INDEX_START)
    end = text.find(INDEX_END, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    return text[start + len(INDEX_START):end].strip()


def adr_checks(
    adr_dir: Path, root: Path, files: list[str], prefix: str = "ADR"
) -> list[Check]:
    """Mechanical ADR hygiene: a status, resolvable ADR references, cited lines that exist.

    `prefix` names the files and references: `ADR-<n>-title.md` and `ADR-<n>` by default,
    `LIFE-<n>-…` with `adr_prefix = "LIFE"`. An amendment is `<prefix>-<n>-A1-title.md`.
    Whether a citation still says what the ADR claims is the adr-reviewer agent's job:
    line contents drift with every edit, so only existence is checked here.
    """
    p_ = re.escape(prefix)
    name = re.compile(rf"^{p_}-(\d+)(-A\d+)?(?:[-.].*)?\.md$")
    found = sorted(adr_dir.glob(f"{prefix}-*.md"))
    adrs = [(int(m.group(1)), bool(m.group(2)), p) for p in found if (m := name.match(p.name))]
    odd = sorted({p.name for p in found} - {p.name for _, _, p in adrs})
    text = {p: p.read_text(encoding="utf-8", errors="replace") for _, _, p in adrs}
    numbers = {n for n, _, _ in adrs}

    nums = [n for n, amend, _ in adrs if not amend]  # an amendment shares its ADR's number
    dupes = [p.name for n, amend, p in adrs if not amend and nums.count(n) > 1]
    out = [
        Check(
            "static",
            "ADRs: names valid, numbers unique",
            not dupes and not odd,
            (f"same number: {dupes} " if dupes else "")
            + (f"not named {prefix}-<n>-title.md: {odd}" if odd else "")
            or f"{len(adrs)} ADR files",
        )
    ]

    bad_status = []
    for _, _, p in adrs:
        m = STATUS_LINE.search(text[p])
        value = m and (m.group(1) or m.group(2) or m.group(3))
        if not value or value.lower() not in ADR_STATUS:
            bad_status.append(p.name)
    out.append(
        Check(
            "static",
            "ADRs: status set",
            not bad_status,
            f"no valid status ({'/'.join(ADR_STATUS)}): {bad_status}"
            if bad_status
            else f"{len(adrs)} ADR files",
        )
    )

    refs: set[int] = set()
    for f in files:
        p = root / f
        if p.suffix in (".md", *SOURCE_EXT, ".toml", ".yml", ".yaml") and p.is_file():
            refs |= {
                int(n)
                for n in re.findall(
                    rf"\b{p_}-(\d+)\b", p.read_text(encoding="utf-8", errors="replace")
                )
            }
    dangling = sorted(refs - numbers)
    out.append(
        Check(
            "static",
            "ADRs: references resolve",
            not dangling,
            f"no file for: {[f'{prefix}-{n:03d}' for n in dangling[:5]]}" if dangling else "clean",
        )
    )

    lengths: dict[str, int] = {}

    def lines(f: str) -> int:
        if f not in lengths:
            lengths[f] = len((root / f).read_text(encoding="utf-8", errors="replace").splitlines())
        return lengths[f]

    broken = []
    for _, _, p in adrs:
        for path, spec in CITATION.findall(text[p]):
            ext = path.rsplit(".", 1)[-1].lower()
            if ext.isdigit() or ("/" not in path and ext not in FILE_EXT):
                continue  # an address such as `127.0.0.1:8000`, not a file
            last = max(int(x) for x in re.split(r"[-,]", spec))
            # Exact path, else a suffix that names one file (`merge_ready.py:156` after a full path).
            cands = [
                f
                for f in files
                if (f == path or f.endswith("/" + path)) and (root / f).is_file()
            ]
            if path in cands:
                cands = [path]
            if not cands:
                broken.append(f"{p.name}: {path}:{spec} (no such file)")
            elif len(cands) > 1:
                broken.append(f"{p.name}: {path}:{spec} (ambiguous: {len(cands)} files; give the path)")
            elif lines(cands[0]) < last:
                broken.append(f"{p.name}: {path}:{spec} (past the end)")
    out.append(
        Check(
            "static",
            "ADRs: cited files and lines exist",
            not broken,
            "; ".join(broken[:3]) + (f" (+{len(broken) - 3})" if len(broken) > 3 else "")
            if broken
            else "clean",
        )
    )
    return out


def findings(
    cmd: str, cwd: Path, match: str, strip: str, ok_exit: list[int] | None = None
) -> set[str] | str:
    """The tool's findings, or why there are none to compare (a string)."""
    code, out = sh(cmd, cwd=cwd)
    if code == 127:
        return "command not found"
    if ok_exit is not None and code not in ok_exit:  # a failed run is not "no findings"
        return f"command failed (exit {code})"
    return {
        re.sub(strip, ":", ln) if strip else ln
        for ln in out.splitlines()
        if re.search(match, ln)
    }


def baselines(entries: list[dict[str, Any]], base: str, workdir: Path) -> None:
    """Each tool's findings (line numbers stripped) must not grow against the base."""
    if not entries:
        return
    tree = workdir / "base_tree"
    shutil.rmtree(tree, ignore_errors=True)
    subprocess.run(
        ["git", "worktree", "add", "-q", "--detach", str(tree), base],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    try:
        for b in entries:
            sub = b.get("cwd", ".")
            values = {"root": str(ROOT / sub)}
            if not (tree / sub).is_dir():  # the area is new on this branch
                old: set[str] | str = set()
            else:
                if b.get("setup"):
                    sh(fill(b["setup"], values), cwd=tree / sub)
                old = findings(
                    fill(b["cmd"], values), tree / sub, b["match"],
                    b.get("strip", ""), b.get("ok_exit"),
                )
            new = findings(
                fill(b["cmd"], values), ROOT / sub, b["match"],
                b.get("strip", ""), b.get("ok_exit"),
            )
            if isinstance(old, str) or isinstance(new, str):
                why = new if isinstance(new, str) else f"on the base: {old}"
                record("static", f"{b['name']}: no new findings", False, why)
                continue
            added = sorted(new - old)
            record(
                "static",
                f"{b['name']}: no new findings",
                not added,
                f"{len(old)} -> {len(new)}" + (f"; new: {added[:3]}" if added else ""),
            )
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(tree)],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )


def static_checks(
    cfg: dict[str, Any], base: str, workdir: Path, allow_lock: bool
) -> None:
    print(f"\n== static (against {base})", flush=True)
    rows, added, mb = changed_files(base)
    if not mb:
        record("static", "merge-base found", False, f"no merge-base with {base}")
        return
    live = [r for r in rows if not r[0].startswith("D")]

    secret = re.compile(cfg.get("secret_pattern", SECRET))
    hits = [ln.strip()[:40] for ln in added if secret.search(ln)]
    record(
        "static",
        "security: no secrets added",
        not hits,
        f"{len(hits)} hit(s)" if hits else "clean",
    )
    paths = [
        ln.strip()[:80]
        for ln in added
        if re.search(cfg.get("machine_path_pattern", MACHINE_PATH), ln)
    ]
    record(
        "static",
        "security: no machine paths added",
        not paths,
        "; ".join(paths[:2]) or "clean",
    )
    bad = [
        r[-1] for r in live if re.search(cfg.get("forbidden_pattern", FORBIDDEN), r[-1])
    ]
    record(
        "static", "security: no env/db files added", not bad, ", ".join(bad) or "clean"
    )

    locks = set(cfg.get("locks", []))
    touched = sorted({r[-1] for r in rows} & locks)
    record(
        "static",
        "supply chain: lock files unchanged",
        not touched or allow_lock,
        f"changed: {touched}"
        + (" (allowed)" if allow_lock else "; rerun with --allow-lock once reviewed")
        if touched
        else "unchanged",
    )

    scope = cfg.get("scope", [])
    outside = [
        r[-1]
        for r in rows
        if scope and not any(r[-1].startswith(s) for s in scope) and r[-1] not in locks
    ]
    record(
        "static",
        "scope: changes inside the declared areas",
        not outside,
        f"{len(rows)} files" + (f"; outside: {outside[:5]}" if outside else ""),
    )

    if "llm_boundary" in cfg:
        llm_boundary(cfg["llm_boundary"])
    if cfg.get("decision_log"):
        decision_log(ROOT / cfg["decision_log"])
    if cfg.get("adr_dir"):
        adr_dir = ROOT / cfg["adr_dir"]
        prefix = cfg.get("adr_prefix", "ADR")
        if not adr_dir.is_dir():
            record("static", "ADRs: directory present", False, f"{cfg['adr_dir']} missing")
        elif not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", prefix):
            record("static", "ADRs: adr_prefix valid", False, f"{prefix!r}: letters and digits, e.g. \"ADR\"")
        else:
            ls = git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
            files = [f for f in ls.split("\0") if f]  # -z: names unquoted, even non-ASCII
            for c in adr_checks(adr_dir, ROOT, files, prefix):
                record(c.group, c.name, c.ok, c.detail)
            if cfg.get("adr_index"):
                index = ROOT / cfg["adr_index"]
                current = index_section(index.read_text(encoding="utf-8")) if index.is_file() else None
                want = adr_index_table(adr_dir, index, prefix)
                record(
                    "static",
                    "ADRs: index current",
                    current == want,
                    "current"
                    if current == want
                    else f"{cfg['adr_index']} "
                    + ("missing or without its index markers" if current is None else "out of date")
                    + ": run `uv run tools/gate/gate.py --write-adr-index`",
                )
    for c in cfg.get("check", []):
        if c.get("phase") == "static":
            code, out = sh(
                c["cmd"], cwd=ROOT / c.get("cwd", "."), timeout=c.get("timeout", 1800)
            )
            record("static", c["name"], code == 0, last_line(out) or f"exit {code}")
    baselines(cfg.get("baseline", []), base, workdir)


# ── live ────────────────────────────────────────────────────────────────────


def wait_http(url: str, seconds: int) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except (OSError, ValueError, http.client.HTTPException):
            # Not ready yet: refused, reset, or a half-started server's bad reply. A probe
            # must never crash the gate (it would leave no results.json behind).
            time.sleep(0.5)
    return False


def start(
    svc: dict[str, Any], env: dict[str, str], log: Path
) -> subprocess.Popen[bytes]:
    out = log.open("wb")
    return subprocess.Popen(
        svc["cmd"],
        shell=True,
        cwd=ROOT / svc.get("cwd", "."),
        env={**base_env(), **env},
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def stop(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    # macOS raises EPERM, not ESRCH, for a process group whose leader has exited.
    except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def live_checks(cfg: dict[str, Any], variant: dict[str, Any], workdir: Path) -> None:
    name = variant.get("name", "default")
    vdir = workdir / name
    vdir.mkdir(parents=True, exist_ok=True)  # service logs land here even with no [[scratch]]
    print(f"\n== live ({name})", flush=True)
    env: dict[str, str] = {"GATE_WORKDIR": str(vdir), "GATE_VARIANT": name}
    for s in cfg.get("scratch", []):
        dst = vdir / "scratch" / Path(s["src"]).name
        src = ROOT / s["src"]
        if not src.exists():
            record(name, f"scratch copy of {s['src']}", False, "source missing")
            return
        snapshot(src, dst)
        env[s["env"]] = fill(s.get("value", "{path}"), {"path": str(dst)})
    env.update(
        {
            k: fill(str(v), {"workdir": str(vdir)})
            for k, v in variant.get("env", {}).items()
        }
    )
    values = {"workdir": str(vdir), "variant": name}
    if variant.get("setup"):
        code, out = sh(fill(variant["setup"], values), env=env)
        if not record(
            name, "variant setup", code == 0, last_line(out) or f"exit {code}"
        ):
            return
    procs = []
    try:
        for svc in cfg.get("service", []):
            # Something already answering the ready URL is not ours: our process would
            # exit with "address in use" while the foreign one passed the probe.
            if svc.get("ready") and wait_http(svc["ready"], 1):
                record(name, f"service {svc['name']} up", False, f"{svc['ready']} answered before start: port in use")
                return
            p = start(svc, env, vdir / f"{svc['name']}.log")
            procs.append(p)
            ok = (
                wait_http(svc["ready"], svc.get("ready_seconds", 60))
                if svc.get("ready")
                else True
            )
            # Ours must still be running, or have exited 0 after backgrounding the server
            # (`docker compose up -d`, `pg_ctl start`). A non-zero exit is a failed start.
            code = p.poll()
            ok = ok and code in (None, 0)
            detail = svc.get("ready", "started") if code in (None, 0) else f"cmd exited {code}"
            if not record(name, f"service {svc['name']} up", ok, detail):
                return
        for c in cfg.get("check", []):
            if c.get("phase", "live") != "live":
                continue
            if c.get("variants") and name not in c["variants"]:
                continue
            code, out = sh(
                fill(c["cmd"], values),
                cwd=ROOT / c.get("cwd", "."),
                env=env,
                timeout=c.get("timeout", 1800),
            )
            (vdir / "logs").mkdir(parents=True, exist_ok=True)
            (vdir / "logs" / (re.sub(r"\W+", "_", c["name"]) + ".log")).write_text(
                out, encoding="utf-8"
            )
            record(name, c["name"], code == 0, last_line(out) or f"exit {code}")
    finally:
        for p in procs:
            stop(p)
        if variant.get("teardown"):
            sh(fill(variant["teardown"], values), env=env)


# ── main ────────────────────────────────────────────────────────────────────


class Tee:
    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, s: str) -> None:
        for st in self.streams:
            st.write(s)

    def flush(self) -> None:
        for st in self.streams:
            st.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--workdir", type=Path, help="output directory, e.g. .e2e/gate-1")
    ap.add_argument(
        "--write-adr-index", action="store_true",
        help="regenerate the ADR index named by adr_index in gate.toml, then exit",
    )
    ap.add_argument("--config", type=Path, default=ROOT / "gate.toml")
    ap.add_argument(
        "--base", help="git ref to compare against (default: gate.toml base)"
    )
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--live-only", action="store_true")
    ap.add_argument("--variants", help="comma-separated subset of [[variant]] names")
    ap.add_argument(
        "--scope", help="comma-separated path prefixes; overrides gate.toml scope"
    )
    ap.add_argument(
        "--allow-lock", action="store_true", help="lock-file change reviewed"
    )
    args = ap.parse_args()

    cfg = tomllib.loads(args.config.read_text(encoding="utf-8"))
    if args.write_adr_index:
        if not (cfg.get("adr_dir") and cfg.get("adr_index")):
            raise SystemExit("gate.toml needs adr_dir and adr_index to write the ADR index")
        index = ROOT / cfg["adr_index"]
        table = adr_index_table(ROOT / cfg["adr_dir"], index, cfg.get("adr_prefix", "ADR"))
        text = index.read_text(encoding="utf-8") if index.is_file() else ""
        block = f"{INDEX_START}\n{table}\n{INDEX_END}"
        if index_section(text) is None:
            text = text.rstrip("\n") + ("\n\n" if text else "") + block + "\n"
        else:
            head, rest = text.split(INDEX_START, 1)
            text = head + block + rest.split(INDEX_END, 1)[1]
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(text, encoding="utf-8")
        print(f"wrote {cfg['adr_index']}")
        return 0
    if args.workdir is None:
        ap.error("--workdir is required")
    base = args.base or cfg.get("base", "main")
    if args.scope:
        cfg["scope"] = [s for s in args.scope.split(",") if s]
    workdir = args.workdir if args.workdir.is_absolute() else ROOT / args.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    log = (workdir / "gate.log").open("w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log)

    print(
        f"gate: {ROOT.name} @ {git('rev-parse', '--short', 'HEAD').strip()} ({time.strftime('%Y-%m-%d %H:%M:%S')})"
    )
    guards = {g: digest(ROOT / g) for g in cfg.get("guard", {}).get("files", [])}

    if not args.live_only:
        static_checks(cfg, base, workdir, args.allow_lock)
    if not args.static_only:
        variants = cfg.get("variant") or [{"name": "default"}]
        wanted = set(args.variants.split(",")) if args.variants else None
        for v in variants:
            if wanted is None or v.get("name", "default") in wanted:
                live_checks(cfg, v, workdir)
        for g, before in guards.items():
            if before == "absent":
                record("all", f"guard: {g} present", False, "missing: it guards nothing")
            else:
                record(
                    "all",
                    f"guard: {g} unchanged",
                    digest(ROOT / g) == before,
                    before[:16],
                )

    failed = [r for r in RESULTS if not r.ok]
    (workdir / "results.json").write_text(
        json.dumps([asdict(r) for r in RESULTS], indent=2), encoding="utf-8"
    )
    run = {
        "head": git("rev-parse", "HEAD").strip(),
        # tracked changes only: untracked files never reach a merge
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no").strip()),
        "static": not args.live_only,
        # a --variants filter leaves live checks unrun, so it is never a full run
        "live": not args.static_only and not args.variants,
        "passed": len(RESULTS) - len(failed),
        "total": len(RESULTS),
    }
    (workdir / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    print(
        f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed"
        + (f"; FAILED: {[f.name for f in failed]}" if failed else "")
    )
    sys.stdout = sys.__stdout__
    log.close()
    return 1 if failed or not RESULTS else 0


if __name__ == "__main__":
    sys.exit(main())
