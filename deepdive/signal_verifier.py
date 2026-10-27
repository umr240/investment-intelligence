"""Deterministic check of LLM-extracted external signals (ADR-057 §2.1-2.2).

Pure functions: no LLM, no network. `verify_signal` checks that a signal's quote
is one substring of the exact text the model saw and that its value is a number
in that quote; `stored_band` caps the model's confidence by the outcome.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

MAX_QUOTE_CHARS = 300  # both prompts' limit
HEADER_LOOKBACK = 500  # source characters before a quote searched for a `%` column header

VERIFIED = "verified"
VERIFIED_TABLE_SCALE = "verified_table_scale"
SCALE_UNCONFIRMED = "scale_unconfirmed"
QUOTE_NOT_IN_SOURCE = "quote_not_in_source"
VALUE_NOT_IN_QUOTE = "value_not_in_quote"
NO_VALUE = "no_value"
MULTIPLE_CANDIDATES = "multiple_candidates"

DROPPED = frozenset({QUOTE_NOT_IN_SOURCE, VALUE_NOT_IN_QUOTE})
_CEILING = {
    VERIFIED: "high",
    VERIFIED_TABLE_SCALE: "medium",
    SCALE_UNCONFIRMED: "low",
    QUOTE_NOT_IN_SOURCE: "not_disclosed",
    VALUE_NOT_IN_QUOTE: "not_disclosed",
    NO_VALUE: "not_disclosed",
}
_BAND_ORDER = ("not_disclosed", "low", "medium", "high")
_SCALES = (Decimal(1), Decimal(10**3), Decimal(10**6), Decimal(10**9))
_SCALE_WORDS = {
    "thousand": Decimal(10**3), "k": Decimal(10**3),
    "million": Decimal(10**6), "m": Decimal(10**6),
    "billion": Decimal(10**9), "b": Decimal(10**9), "bn": Decimal(10**9),
    "mm": Decimal(10**6), "mn": Decimal(10**6), "mln": Decimal(10**6),
    "trillion": Decimal(10**12), "tn": Decimal(10**12),
}  # fmt: skip
# Any scale word anywhere in a quote: an unscaled match beside one is never better than low.
_SCALE_TOKEN = re.compile(r"\b(?:thousand|million|billion|trillion|bn|mm|mn|mln|tn|[kmb])s?\b")
# How a document states a table scale: "in millions", "(in US $ millions" (SHOP), "amounts in
# USD million", "in thousands of U.S. dollars", "($000s)", "(in 000's)", "($M)", "($mm)".
_DOC_SCALE = re.compile(
    r"\bin (?:(?:us|u\.s\.|usd)\s?)?(?:\$\s?)?(thousand|million|billion)s?\b"
    r"|\bin (000)'?s\b|\(\$\s?(000)'?s?\)|\(\$\s?(mm|m|b)\)"
)
_DOC_SCALE_VALUE = {
    "thousand": Decimal(10**3), "000": Decimal(10**3),
    "million": Decimal(10**6), "m": Decimal(10**6), "mm": Decimal(10**6),
    "billion": Decimal(10**9), "b": Decimal(10**9),
}  # fmt: skip
_PERCENT_WORD = re.compile(r"%|\bpercent\b")

# One number in a normalised (case-folded) quote: optional sign, "(" and "$", digits,
# optional ")", optional unit or scale. The lookbehind skips digits inside words (Q1, FY2025).
_NUMBER = re.compile(
    r"(?P<neg>[-−–]\s?)?(?P<open>\()?(?P<cur>\$)?(?P<neg2>[-−])?\s?"
    r"(?<![\w.,])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?P<close>\))?"
    r"(?:(?P<pct>\s?%|\s(?:percent)\b|\s?(?:bps?|basis points?)\b)"
    r"|(?P<word>\s(?:thousand|million|billion|trillion|bn|mm|mn|mln|tn)s?\b)"
    r"|(?P<suffix>bn|mm|tn|[kmb])(?!-\d)\b)?"
)
_RANGE_JOIN = re.compile(r"^\s*(?:–|—|-|to)\s*$")


@dataclass(frozen=True)
class ParsedNumber:
    value: Decimal  # as written, sign applied
    unit: str  # "currency" | "pct" | "bare"
    scale: Decimal | None  # stated by the quote itself ("million", "M"); None if not
    start: int
    end: int
    bps: bool = False  # written in basis points; value already in percentage points
    unknown_unit: bool = False  # letters glued on that the grammar does not know ("2.0x")


@dataclass
class Verification:
    outcome: str
    ceiling: str
    flags: list[str] = field(default_factory=list)
    matched: str | None = None  # the quote number the value matched
    quote_at: int | None = None  # offset of the quote in the normalised source
    replaced: dict[str, object] | None = None  # the row a re-run replaced (§4)

    @property
    def kept(self) -> bool:
        return self.outcome not in DROPPED and self.outcome != NO_VALUE

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, default=str)


def normalise(text: str) -> str:
    """NFKC, non-breaking spaces and curly quotes made plain, whitespace collapsed, case-folded."""
    t = unicodedata.normalize("NFKC", text)
    t = t.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x00A0: " "})
    return re.sub(r"\s+", " ", t).strip().casefold()


def parse_numbers(quote: str) -> list[ParsedNumber]:
    """Numbers in a normalised quote by the ADR-057 §2.1.2 grammar."""
    out: list[ParsedNumber] = []
    for m in _NUMBER.finditer(quote):
        digits = m.group("num")
        has_parens = bool(m.group("open") and m.group("close"))
        unit_word = m.group("pct") or m.group("word") or m.group("suffix")
        if has_parens and not m.group("cur") and not unit_word and re.fullmatch(r"\d{1,2}", digits):
            continue  # footnote marker: (4), also glued as in 87.73(1)
        if (
            re.fullmatch(r"\d{4}", digits)
            and 1900 <= int(digits) <= 2099
            and not (m.group("cur") or unit_word or has_parens)
        ):
            continue  # a bare year
        try:
            value = Decimal(digits.replace(",", ""))
        except InvalidOperation:
            continue
        start = m.start()
        # A dash glued to the number just parsed joins a range ("120-125%", "10%-12%"); any
        # other dash is a sign ("NRR 118% -5%", "FY 2025 -5%"), erring toward a missing value.
        neg = m.group("neg")
        joins = (
            neg is not None and neg == neg.strip() and bool(out) and out[-1].end == start
            and out[-1].value <= value  # a range ascends: "118%-5%" is a minus
        )  # fmt: skip
        if joins:
            start = m.end("neg")
        if has_parens or m.group("neg2") or (m.group("neg") and not joins):
            value = -value
        suffix = m.group("suffix")  # never before "-digit": "Rule 10b-5" (in the regex)
        bps = False
        scale: Decimal | None = None
        if m.group("pct"):
            unit = "pct"
            if "b" in m.group("pct"):  # "bp", "bps", "basis point(s)"
                value, bps = value / 100, True  # bps and basis points, in percentage points
        elif m.group("word") or suffix:
            unit = "currency"
            key = (m.group("word") or "").strip() or suffix or ""
            scale = _SCALE_WORDS[key if key in _SCALE_WORDS else key[:-1]]  # plural: "billions"
        elif m.group("cur"):
            unit = "currency"
        else:
            unit = "bare"
        unknown = re.match(r"[a-z]", quote[m.end() : m.end() + 1]) is not None
        out.append(ParsedNumber(value, unit, scale, start, m.end(), bps, unknown))
    # A range ("120–125%", "$5-6 billion") is two numbers; the first takes the second's
    # unit and stated scale when it has none of its own.
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        takes_unit = a.unit == "bare" and b.unit != "bare"
        takes_scale = a.unit in ("bare", "currency") and a.scale is None and b.scale is not None
        if (takes_unit or takes_scale) and _RANGE_JOIN.match(quote[a.end : b.start]):
            value = a.value / 100 if b.bps and a.unit == "bare" else a.value
            unit = b.unit if a.unit == "bare" else a.unit
            out[i] = ParsedNumber(value, unit, b.scale, a.start, a.end, b.bps, a.unknown_unit)
    return out


def _to_decimal(value: float) -> Decimal | None:
    try:
        return Decimal(repr(value))
    except (InvalidOperation, ValueError):
        return None


def verify_signal(value: float | None, quote: str, unit: str, source_text: str) -> Verification:
    """ADR-057 §2.1. `source_text` is exactly what the model was sent."""
    if value is None:
        return Verification(NO_VALUE, _CEILING[NO_VALUE])
    q, src = normalise(quote), normalise(source_text)
    at = src.find(q) if q else -1
    if not q or len(q) > MAX_QUOTE_CHARS or at < 0:
        return Verification(QUOTE_NOT_IN_SOURCE, _CEILING[QUOTE_NOT_IN_SOURCE])
    target = _to_decimal(value)
    numbers = parse_numbers(q)
    if target is None:
        return Verification(VALUE_NOT_IN_QUOTE, _CEILING[VALUE_NOT_IN_QUOTE], quote_at=at)

    doc_scales = {
        _DOC_SCALE_VALUE[next(g for g in groups if g)] for groups in _DOC_SCALE.findall(src)
    }
    scale_nearby = _SCALE_TOKEN.search(q) is not None
    rank = {VERIFIED: 0, VERIFIED_TABLE_SCALE: 1, SCALE_UNCONFIRMED: 2}
    best: tuple[str, ParsedNumber] | None = None
    for n in numbers:
        outcome: str | None = None
        if unit == "pct":
            if n.unit == "pct" and n.value == target:
                outcome = VERIFIED
            elif n.unit == "bare" and n.value == target:
                header = src[max(0, at - HEADER_LOOKBACK) : at]
                outcome = (
                    VERIFIED_TABLE_SCALE if _PERCENT_WORD.search(header) else SCALE_UNCONFIRMED
                )
        elif n.unit != "pct":
            scales = (n.scale,) if n.scale is not None else _SCALES
            for s in scales:
                if n.value * s != target:
                    continue
                if n.scale is not None:
                    outcome = VERIFIED
                elif s == 1:
                    # "$5 – 6 billion", "$1.5 B": the scale may belong to this number; in a
                    # document stated "in millions" a bare figure may be a table cell (§4).
                    outcome = SCALE_UNCONFIRMED if scale_nearby or doc_scales else VERIFIED
                elif s in doc_scales:
                    outcome = VERIFIED_TABLE_SCALE
                else:
                    outcome = SCALE_UNCONFIRMED
                break
        if outcome and n.unknown_unit:
            outcome = SCALE_UNCONFIRMED  # an unrecognised unit may be a scale ("1.5bn" before bn)
        if outcome and (best is None or rank[outcome] < rank[best[0]]):
            best = (outcome, n)
    if best is None:
        return Verification(VALUE_NOT_IN_QUOTE, _CEILING[VALUE_NOT_IN_QUOTE], quote_at=at)

    outcome, hit = best
    flags: list[str] = []
    hit_size = abs(hit.value * (hit.scale or 1))
    for n in numbers:
        if n is hit or n.unit != hit.unit:
            continue
        size = abs(n.value * (n.scale or 1))
        if hit_size and size != hit_size and Decimal("0.5") <= size / hit_size <= 2:
            flags.append(MULTIPLE_CANDIDATES)
            break
    ceiling = "low" if flags else _CEILING[outcome]
    return Verification(outcome, ceiling, flags, matched=str(hit.value), quote_at=at)


def stored_band(model_band: str, ceiling: str) -> str:
    """The lower of the model's band and the verifier's ceiling (§2.2)."""
    m = model_band if model_band in _BAND_ORDER else "not_disclosed"
    return min(m, ceiling, key=_BAND_ORDER.index)
