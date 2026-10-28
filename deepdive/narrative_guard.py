"""
Anti-hallucination validator for AI-generated narratives.

Runs AFTER the LLM produces a NarrativeBody and BEFORE the result is shown
to the user. Its job is to catch the failure modes the system prompt asks
the model to avoid, because system prompts are guidance, not enforcement.

Checks performed (each emits a string warning into `guard_warnings`):

  1. NUMBER PROVENANCE
     For each NumericClaim in any bull/bear point, walk `field_path` into
     the ScorecardView dict; the resolved value must, after normalisation,
     match the claim's `value` string. Mismatches (or unresolvable paths)
     are flagged.

  2. TEXT-EMBEDDED NUMBERS
     Headlines and details may contain numbers that the LLM forgot to
     declare in `numeric_claims`. We extract every number-looking token
     from the prose and require it to appear in the whitelisted-numbers
     set built from the view (with %, $, B/M/K, ratios all normalised).
     Unwhitelisted numbers are the most common hallucination vector —
     these get flagged.

  3. FRAMEWORK CITATIONS
     Every framework_code on bull/bear points must appear in `view.frameworks`
     and not be `is_unfeasible=True`.

  4. RISK GROUNDING
     Every RiskFactor.grounded_in must resolve to either:
       - a feasible framework code present in view, or
       - an overlay_trigger.trigger_id present in view, or
       - a substring of a fetch_data_gaps entry.

  5. CAVEAT FIDELITY
     If view has data gaps but body.data_caveats is empty → warning.
     (We do NOT enforce 1-to-1 mapping — the LLM is allowed to summarise.)

Schema v2 (ADR-045) bodies go to `validate_v2`: the model cites field IDs and
writes numbers only as placeholders, so checks 1-2 become "every ID exists" and
"no literal number outside the whitelist", and the verdict must equal the
mapped composite verdict.

The validator NEVER raises. It returns a list[str] of warnings; an empty
list means the narrative is clean. The caller (narrative.generate_narrative)
flags status=guard_failed when warnings is non-empty so the CLI can show
the warnings to the human reader, who then decides whether to trust it.
"""
from __future__ import annotations

import re
from typing import Any

from config.verdicts import narrative_verdict
from deepdive.narrative_output import NarrativeBody, NarrativeBodyV2
from deepdive.scorecard_view import ScorecardView

# Numbers the LLM might write: 12.4%, $2.1B, 0.85, 6/9, 1.2x, 4,500
# Excludes years (4-digit standalone), simple counts (1-3 digit lone integers
# without a unit) — those are too frequent in prose to police.
_NUMBER_RE = re.compile(
    r"""
    (?<![A-Za-z])                # not part of a word
    (?:\$)?                      # optional dollar
    (?P<num>
        \d{1,3}(?:,\d{3})+(?:\.\d+)?  # 4,500 / 1,234,567 / 1,612.3
        | \d+\.\d+               # 12.4 / 0.85
        | \d+/\d+                # 6/9
        | \d{2,}                 # bare 2+ digit (filters years/single digits)
    )
    (?!\s?-\s?(?:week|day|month|year|quarter)s?\b)  # "52-week high" is a label
    (?:                          # a unit, or no letter: drops "DEF 14A", "13F"
        (?P<unit>\s?[%xX]|\s?(?:bps|T|B|M|K|tn|bn|bln|mn|mln|trn))
        | (?![A-Za-z])
    )
    """,
    re.VERBOSE,
)


def validate(body: NarrativeBody | NarrativeBodyV2, view: ScorecardView) -> list[str]:
    """Return a list of guard-warning strings. Empty == clean."""
    if isinstance(body, NarrativeBodyV2):
        return validate_v2(body, view)
    warnings: list[str] = []

    view_dict = view.to_dict()
    whitelist = _build_whitelist(view)
    whitelist_floats = _collect_floats(view_dict)
    feasible_codes = {fv.code for fv in view.frameworks if not fv.is_unfeasible}
    all_framework_codes = {fv.code for fv in view.frameworks}
    overlay_ids = {t.trigger_id for t in view.overlay_triggers}
    fetch_gaps = list(view.fetch_data_gaps or [])

    # 1. NUMBER PROVENANCE — declared numeric_claims must resolve
    for section_name, points in (("bull", body.bull), ("bear", body.bear)):
        for i, p in enumerate(points):
            for j, claim in enumerate(p.numeric_claims):
                resolved = _walk_path(view_dict, claim.field_path)
                if resolved is None:
                    warnings.append(
                        f"{section_name}[{i}].numeric_claims[{j}]: "
                        f"field_path '{claim.field_path}' does not exist in view"
                    )
                    continue
                if not _value_matches(claim.value, resolved):
                    warnings.append(
                        f"{section_name}[{i}].numeric_claims[{j}]: claim value "
                        f"'{claim.value}' does not match view value "
                        f"'{resolved}' at '{claim.field_path}'"
                    )

    # 2. TEXT-EMBEDDED NUMBERS — every number in headline/detail must trace
    #    to a whitelisted scorecard number (exact-string fast path, then
    #    fuzzy float fallback for soft-rounding cases like "14%" vs "14.3%").
    for section_name, points in (("bull", body.bull), ("bear", body.bear)):
        for i, p in enumerate(points):
            for field_name, text in (("headline", p.headline), ("detail", p.detail)):
                for tok, floats, unit in _extract_tokens_and_floats(text):
                    if _token_is_whitelisted(tok, floats, whitelist, whitelist_floats, unit):
                        continue
                    warnings.append(
                        f"{section_name}[{i}].{field_name}: number '{tok}' "
                        f"not in scorecard whitelist (possible hallucination)"
                    )

    # one_liner numbers
    for tok, floats, unit in _extract_tokens_and_floats(body.one_liner):
        if _token_is_whitelisted(tok, floats, whitelist, whitelist_floats, unit):
            continue
        warnings.append(
            f"one_liner: number '{tok}' not in scorecard whitelist "
            f"(possible hallucination)"
        )

    # 3. FRAMEWORK CITATIONS
    for section_name, points in (("bull", body.bull), ("bear", body.bear)):
        for i, p in enumerate(points):
            warnings += _framework_code_warnings(
                f"{section_name}[{i}]", p.framework_codes, all_framework_codes, feasible_codes
            )

    # 4. RISK GROUNDING — accept framework codes, overlay trigger IDs,
    # data-gap substrings, OR any view field path that resolves (e.g. the
    # LLM noticed `company.ceo_equity_pct_state` and used it as grounding —
    # legitimate, not a hallucination).
    for i, r in enumerate(body.risks):
        warnings += _risk_grounding_warnings(
            i, r.grounded_in, view_dict, feasible_codes, overlay_ids, fetch_gaps
        )

    # 5. CAVEAT FIDELITY
    warnings += _caveat_warnings(view, body.data_caveats)
    return warnings


# A trigger condition states a threshold the model proposes ("falls below 10%"),
# which no view holds; every other text is a claim, so a literal number in it must
# be one the view holds (§2.2). v1 checked only the one-liner and the points.
_PROPOSED_THRESHOLD = re.compile(r"^triggers\[\d+\]\.condition$")


def validate_v2(body: NarrativeBodyV2, view: ScorecardView) -> list[str]:
    """Guard warnings for a schema v2 body (ADR-045 §2.2, §2.3). Empty == clean."""
    from deepdive.narrative_render import PLACEHOLDER, placeholders, prose, render_text

    warnings: list[str] = []
    fields = view.citable_fields()
    view_dict = view.to_dict()
    whitelist = _build_whitelist(view)
    whitelist_floats = _collect_floats(view_dict)
    feasible_codes = {fv.code for fv in view.frameworks if not fv.is_unfeasible}
    all_framework_codes = {fv.code for fv in view.frameworks}
    overlay_ids = {t.trigger_id for t in view.overlay_triggers}
    fetch_gaps = list(view.fetch_data_gaps or [])

    # 1. Every placeholder names a citable field, and nothing is left unrendered.
    for path, text in prose(body):
        unknown = [f for f in placeholders(text) if f not in fields]
        warnings += [f"{path}: placeholder '{{{f}}}' is not a citable field" for f in unknown]
        if not unknown and re.search(r"[{}]", render_text(text, fields)):
            warnings.append(f"{path}: unrendered placeholder or stray brace")
        # 2. A literal number in a claim is a guard error unless the view holds it.
        if not _PROPOSED_THRESHOLD.match(path):
            for tok, floats, unit in _extract_tokens_and_floats(PLACEHOLDER.sub(" ", text)):
                if not _token_is_whitelisted(tok, floats, whitelist, whitelist_floats, unit):
                    warnings.append(
                        f"{path}: literal number '{tok}' not in scorecard whitelist "
                        "(cite a field with a placeholder)"
                    )

    for section_name, points in (("bull", body.bull), ("bear", body.bear)):
        for i, p in enumerate(points):
            warnings += [
                f"{section_name}[{i}].numeric_claims: '{c.field_id}' is not a citable field"
                for c in p.numeric_claims
                if c.field_id not in fields
            ]
            warnings += _framework_code_warnings(
                f"{section_name}[{i}]", p.framework_codes, all_framework_codes, feasible_codes
            )

    # 3. The model explains the deterministic verdict; it does not choose it (§3).
    expected = narrative_verdict(view.composite.verdict)
    if body.verdict.value != expected:
        warnings.append(
            f"verdict: '{body.verdict.value}' but the composite verdict "
            f"'{view.composite.verdict}' maps to '{expected}'"
        )
    if not body.triggers:  # what would flip it, for an exclude or research-only verdict too
        warnings.append("triggers: empty; name what would change the verdict")
    warnings += [
        f"triggers[{i}]: '{t.field_id}' is not a citable field"
        for i, t in enumerate(body.triggers)
        if t.field_id not in fields
    ]

    for i, r in enumerate(body.risks):
        if r.grounded_in.strip() not in fields:
            warnings += _risk_grounding_warnings(
                i, r.grounded_in, view_dict, feasible_codes, overlay_ids, fetch_gaps
            )
    warnings += _caveat_warnings(view, body.data_caveats)
    return warnings


def _framework_code_warnings(
    where: str, codes: list[str], all_codes: set[str], feasible: set[str]
) -> list[str]:
    out = []
    for code in codes:
        if code not in all_codes:
            out.append(f"{where}.framework_codes: '{code}' is not a recognised framework")
        elif code not in feasible:
            out.append(
                f"{where}.framework_codes: '{code}' "
                f"is unfeasible for this ticker — cannot ground a point"
            )
    return out


def _risk_grounding_warnings(
    i: int,
    grounded_in: str | None,
    view_dict: dict[str, Any],
    feasible: set[str],
    overlay_ids: set[str],
    fetch_gaps: list[str],
) -> list[str]:
    g = (grounded_in or "").strip()
    if not g:
        return [f"risks[{i}]: empty grounded_in"]
    if g in feasible or g in overlay_ids or any(g in gap or gap in g for gap in fetch_gaps):
        return []
    # Field-path fallback: a dotted path into the view dict, or a bare leaf name.
    if ("." in g and _walk_path(view_dict, g) is not None) or _view_has_field_name(view_dict, g):
        return []
    return [
        f"risks[{i}]: grounded_in='{g}' does not match any framework, "
        f"overlay trigger, data gap, or view field"
    ]


def _caveat_warnings(view: ScorecardView, caveats: list[str]) -> list[str]:
    has_any_gap = bool(view.fetch_data_gaps) or any(fv.data_gaps for fv in view.frameworks)
    if has_any_gap and not caveats:
        return ["data_caveats is empty but view has data_gaps — caveats elided"]
    return []


# ── Internals ────────────────────────────────────────────────────────────


def _view_has_field_name(d: Any, name: str) -> bool:
    """Return True if `name` is a key anywhere in the nested view dict
    AND its value is non-null. Used to validate bare-name risk grounding
    like 'ceo_equity_pct_state' which is a real field but not at the top.
    """
    if isinstance(d, dict):
        for k, v in d.items():
            if k == name and v is not None and v != "":
                return True
            if _view_has_field_name(v, name):
                return True
    elif isinstance(d, (list, tuple)):
        for item in d:
            if _view_has_field_name(item, name):
                return True
    return False


def _walk_path(d: Any, path: str) -> Any:
    """Walk dotted path into a nested dict/list/tuple. Returns None if missing.

    Tuples are treated as lists because dataclasses.asdict preserves tuples
    but the JSON the LLM sees renders them as arrays — so the LLM's
    field_path indices match list-style access either way.
    """
    cur: Any = d
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, (list, tuple)):
            try:
                idx = int(part)
            except ValueError:
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def _value_matches(claim: str, resolved: Any) -> bool:
    """Loose equality: normalise both sides into a single canonical number.

    Accepts the LLM writing "18.3%" when the view has 0.183, "$2.1B" when
    view has 2_100_000_000, "6/9" when the signal dict has 6 + 9 separately
    (we just check both halves appear). Boolean view values match the LLM
    writing "0"/"false"/"no" (False) or "1"/"true"/"yes" (True) — common
    when an LLM encodes a flag numerically. Tolerance ±2.5% relative.
    """
    if resolved is None:
        return False

    if isinstance(resolved, bool):
        c = claim.strip().lower()
        if resolved:
            return c in {"1", "true", "yes", "y"}
        return c in {"0", "false", "no", "n"}

    claim_nums = _extract_normalised(claim)
    resolved_strs = _coerce_resolved(resolved)
    resolved_nums: set[float] = set()
    for s in resolved_strs:
        resolved_nums.update(_extract_normalised(s))

    if not claim_nums:
        # Claim has no numeric token — only allow if `resolved` stringifies to claim
        return claim.strip().lower() == str(resolved).strip().lower()

    # Tolerance bumped from 0.5% to 2.5% to match prose-token tolerance —
    # the LLM legitimately rounds for display ($5.14T → $5.1T = 0.78% off,
    # which exceeds 0.5% but isn't a fabrication). True hallucinations
    # are orders of magnitude off, so 2.5% comfortably catches them.
    tol = _PROSE_FUZZY_TOL
    for cn in claim_nums:
        for rn in resolved_nums:
            if cn == 0.0 and rn == 0.0:
                return True
            if rn == 0.0:
                continue
            if abs(cn - rn) / max(abs(rn), 1e-9) <= tol:
                return True
            # Tolerate the percentage encoding ambiguity: claim 18.3 vs view 0.183
            if abs(cn / 100.0 - rn) / max(abs(rn), 1e-9) <= tol:
                return True
            if abs(cn * 100.0 - rn) / max(abs(rn), 1e-9) <= tol:
                return True
    return False


def _coerce_resolved(v: Any) -> list[str]:
    """Stringify a resolved value (possibly nested) for whitelist building."""
    if v is None:
        return []
    if isinstance(v, (int, float)):
        return [str(v)]
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        out: list[str] = []
        for vv in v.values():
            out.extend(_coerce_resolved(vv))
        return out
    if isinstance(v, list):
        out = []
        for item in v:
            out.extend(_coerce_resolved(item))
        return out
    return [str(v)]


def _extract_numbers(text: str) -> list[str]:
    """Extract human-form numeric tokens from prose for whitelist checking."""
    out: list[str] = []
    for m in _NUMBER_RE.finditer(text):
        token = m.group(0).strip()
        out.append(_normalise_token(token))
    return out


# Soft-match tolerance for prose-embedded numbers. ±2.5% relative lets the
# LLM round "14.3%" down to "14%" without firing, while still flagging
# fabricated values that have no near match in the view (e.g. "$77.7B").
_PROSE_FUZZY_TOL = 0.025


def _extract_tokens_and_floats(text: str) -> list[tuple[str, set[float], str]]:
    """Extract each prose number, its CANONICAL float, and its unit kind.

    "Canonical" = the single value the LLM literally wrote. "999.9%" emits
    {999.9} (not also {9.999}). The matcher then handles cross-form fuzzy
    matching (literal-vs-fraction storage in the view) without polluting
    the candidate set with secondary interpretations that fuzzy-match
    unrelated structural constants.
    """
    out: list[tuple[str, set[float], str]] = []
    for m in _NUMBER_RE.finditer(text):
        raw = m.group("num")
        unit = (m.group("unit") or "").strip().lower()
        tok = _normalise_token(m.group(0).strip())

        floats: set[float] = set()
        try:
            if "/" in raw:
                a, b = raw.split("/")
                floats.add(float(a))
                if float(b) != 0:
                    floats.add(float(a) / float(b))
            else:
                n = float(raw.replace(",", ""))
                if unit in ("t", "tn", "trn"):
                    floats.add(n * 1e12)
                elif unit in ("b", "bn", "bln"):
                    floats.add(n * 1e9)
                elif unit in ("m", "mn", "mln"):
                    floats.add(n * 1e6)
                elif unit in ("k",):
                    floats.add(n * 1e3)
                elif unit in ("bps",):
                    floats.add(n)            # raw bps count
                    floats.add(n / 10_000.0)  # decimal form
                else:
                    floats.add(n)
        except ValueError:
            pass
        out.append((tok, floats, unit))
    return out


def _token_is_whitelisted(
    tok: str,
    floats: set[float],
    whitelist: set[str],
    whitelist_floats: set[float],
    unit: str = "",
) -> bool:
    """Fast string check first; unit-respecting fuzzy float check as fallback.

    A `%`-suffixed prose token may match a stored fraction (×100 scaling)
    OR a stored literal percent (raw match), but NOT a structural constant
    like 10.0 (which is the "9.999 vs 10.0" false match we eliminated).
    """
    if tok in whitelist:
        return True

    is_percent = unit == "%"

    # Sign-insensitive matching: prose "$18.2M loss" → magnitude 18.2M, but
    # view stores -18,200,000 — these refer to the same number, sign is
    # contextual in financial writing ("loss of $X" implies negative).
    for f in floats:
        for w in whitelist_floats:
            af, aw = abs(f), abs(w)
            if af == 0.0 and aw == 0.0:
                return True
            if aw == 0.0:
                continue
            if abs(af - aw) / aw <= _PROSE_FUZZY_TOL:
                if is_percent:
                    if aw <= 1000.0:
                        return True
                else:
                    return True
            if is_percent:
                if abs(af - aw * 100.0) / max(aw * 100.0, 1e-9) <= _PROSE_FUZZY_TOL:
                    return True
    return False


# Keys whose values are scaffolding/structure, not data. Excluded from the
# float whitelist so prose tokens cannot fuzzy-match them. (`max_score=10.0`
# would otherwise let "999.9%" pass via the 9.999/10.0 ≈ match.)
_EXCLUDED_KEYS = frozenset({
    "max_score",
    "schema_version",
    "mode_used",
    "mode_resolved",
})


def _collect_floats(node: Any) -> set[float]:
    """Recursively collect every numeric value in a view dict.

    Strings that contain numbers (e.g. "22.6%") have their numeric content
    extracted via _extract_normalised. Booleans are skipped. Values under
    `_EXCLUDED_KEYS` paths are skipped (structural constants).
    """
    out: set[float] = set()
    _walk_collect_floats(node, out, last_key="")
    return out


def _walk_collect_floats(node: Any, out: set[float], *, last_key: str) -> None:
    if node is None:
        return
    if last_key in _EXCLUDED_KEYS:
        return
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        out.add(float(node))
        return
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_collect_floats(v, out, last_key=str(k))
        return
    if isinstance(node, (list, tuple)):
        for v in node:
            _walk_collect_floats(v, out, last_key=last_key)
        return
    if isinstance(node, str):
        out.update(_extract_normalised(node))


def _normalise_token(tok: str) -> str:
    """Canonical form: strip $, %, x, commas, spaces; preserve B/M/K/bps suffix."""
    t = tok.strip()
    t = t.replace("$", "").replace(",", "").replace(" ", "")
    return t.lower()


def _extract_normalised(text: str) -> set[float]:
    """Extract all numbers in `text` and normalise to a float set.

    Handles %, B/M/K/bn/mln/bps suffixes, x/X multipliers, fractions a/b.
    """
    out: set[float] = set()
    for m in _NUMBER_RE.finditer(text):
        raw = m.group("num")
        unit = (m.group("unit") or "").strip().lower()
        try:
            if "/" in raw:
                a, b = raw.split("/")
                if float(b) != 0:
                    out.add(float(a) / float(b))
                out.add(float(a))
                continue
            n = float(raw.replace(",", ""))
        except ValueError:
            continue

        if unit in ("%",):
            out.add(n / 100.0)
            out.add(n)
        elif unit in ("x",):
            out.add(n)
        elif unit in ("bps",):
            out.add(n / 10_000.0)
            out.add(n)
        elif unit in ("t", "tn", "trn"):
            out.add(n * 1e12)
        elif unit in ("b", "bn", "bln"):
            out.add(n * 1e9)
        elif unit in ("m", "mn", "mln"):
            out.add(n * 1e6)
        elif unit in ("k",):
            out.add(n * 1e3)
        else:
            out.add(n)
    return out


def _build_whitelist(view: ScorecardView) -> set[str]:
    """Build the canonical set of number-tokens the LLM is allowed to write.

    Walks the entire view dict, extracts every numeric value, emits human-form
    representations: raw, percent (×100, 1 dp + 2 dp), $XB / $XM / $XK forms,
    integer/float forms. Anything outside this set in narrative prose
    triggers a warning. Structural keys (max_score etc.) are skipped.
    """
    out: set[str] = set()
    _walk_collect(view.to_dict(), out, last_key="")
    return out


def _walk_collect(node: Any, out: set[str], *, last_key: str) -> None:
    if node is None:
        return
    if last_key in _EXCLUDED_KEYS:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_collect(v, out, last_key=str(k))
        return
    if isinstance(node, (list, tuple)):
        for v in node:
            _walk_collect(v, out, last_key=last_key)
        return
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        _add_number_forms(float(node), out)
        return
    if isinstance(node, str):
        # Strings often contain pre-formatted numbers like "18.3%" or "$2.1B"
        for tok in _extract_numbers(node):
            out.add(tok)
        # Also extract numeric content for whitelist
        for n in _extract_normalised(node):
            _add_number_forms(n, out)
        return


def _add_number_forms(n: float, out: set[str]) -> None:
    """Emit the human-form representations of a single number."""
    if n != n:  # NaN
        return
    out.add(_normalise_token(f"{n}"))
    out.add(_normalise_token(f"{n:.1f}"))
    out.add(_normalise_token(f"{n:.2f}"))

    # Integer form
    if abs(n - round(n)) < 1e-9:
        out.add(str(int(round(n))))

    # Percent forms (covers 0.183 -> 18.3% and 18.3 -> 18.3%)
    pct1 = n * 100.0
    out.add(_normalise_token(f"{pct1:.1f}%"))
    out.add(_normalise_token(f"{pct1:.2f}%"))
    out.add(_normalise_token(f"{n:.1f}%"))
    out.add(_normalise_token(f"{n:.2f}%"))

    # Magnitude forms — $X.XB / $X.XM / $X.XK
    if abs(n) >= 1e9:
        out.add(_normalise_token(f"{n / 1e9:.1f}b"))
        out.add(_normalise_token(f"{n / 1e9:.2f}b"))
    if abs(n) >= 1e6:
        out.add(_normalise_token(f"{n / 1e6:.1f}m"))
        out.add(_normalise_token(f"{n / 1e6:.2f}m"))
    if abs(n) >= 1e3:
        out.add(_normalise_token(f"{n / 1e3:.1f}k"))
        out.add(_normalise_token(f"{n / 1e3:.2f}k"))

    # x-multiplier (DOL / leverage style "2.8x")
    out.add(_normalise_token(f"{n:.1f}x"))
    out.add(_normalise_token(f"{n:.2f}x"))
