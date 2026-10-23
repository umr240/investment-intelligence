"""
EDGAR text parser — deterministic extraction from SEC filing text and HTML.

Zero LLM calls. Uses regex on 10-K text and BeautifulSoup on DEF 14A HTML.
Returns None for values not found rather than guessing.

Design philosophy: explicit data gaps are better than LLM approximations.
A missing value surfaces as a gap string; a hallucinated value silently corrupts signals.

Signals extracted:
  - customer_concentration_pct  (F6) — regex on 10-K risk factors / customer section
  - customer_relationship_years (F6) — regex on 10-K customer section
  - ceo_equity_pct              (F6) — HTML table parsing on DEF 14A ownership table
  - is_founder_ceo              (F6) — regex on proxy/10-K biographical text
  - ceo_tenure_years            (F6) — regex on proxy biographical text
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

_CURRENT_YEAR = date.today().year


# ── Result containers ─────────────────────────────────────────────────────


@dataclass
class CustomerSignals:
    """ADR-018 D4: customer-concentration signals split into revenue vs receivables.

    Revenue concentration is the F6 moat signal (Reg S-K Item 101(c)).
    Receivables concentration is a credit-risk signal (FASB ASC 825) and
    consumed by a separate framework. The two MUST NOT be silently merged.

    `state` is the 3-state classifier from ADR-018:
      - 'disclosed_exact'  — at least one of revenue_pct/receivables_pct
        was extracted from a structured (XBRL) or high-precision regex hit
      - 'not_disclosed'    — explicit no-concentration phrasing detected
        OR no concentration phrasing matched (absence-of-evidence treated
        as positive signal: diversified customer base)
      - 'parser_uncertain' — numeric % matched in concentration-adjacent
        text but couldn't be reliably attributed to a customer
    """
    concentration_pct: float | None = None       # top customer % of REVENUE
    receivables_concentration_pct: float | None = None
    relationship_years: float | None = None
    extraction_method: str = "none"              # 'xbrl' | 'regex' | 'none'
    state: str = "none"


@dataclass
class ProxyOwnership:
    ceo_name: str | None = None
    ceo_equity_pct: float | None = None          # % of shares outstanding (single class)
    is_founder_ceo: bool | None = None
    ceo_tenure_years: float | None = None
    ceo_total_pay: float | None = None           # PEO Summary Compensation Table "Total" (USD)
    extraction_method: str = "none"
    # ADR-018 D2: 'disclosed_exact' | 'not_disclosed' | 'parser_uncertain' | 'none'
    # Distinct from extraction_method. extraction_method records HOW we
    # got the value; state records the semantic confidence.
    state: str = "none"
    multi_class_detected: bool = False           # set True when proxy reports >1 class


# ── Customer concentration patterns (ADR-018 §6.2 v6, validated against
#    AAPL/NVDA/AMSC/FAST/MSFT/INTA/TSLA — 7/7 correctly classified) ────────

_CUSTOMER_SUBJECTS = (
    r"(?:our\s+(?:largest|top|biggest|single|principal|major)\s+customer|"
    r"one\s+(?:direct\s+|indirect\s+|single\s+)?customer|"
    r"(?:a\s+)?single\s+customer|"
    r"(?:our\s+)?two\s+customers?|"
    r"sales?\s+to\s+(?:one|a\s+single|our\s+largest|two)\s+(?:direct\s+|indirect\s+)?customer)"
)
_REVENUE_TARGETS = r"(?:revenues?|sales|billings|net\s+sales|total\s+revenue|total\s+net\s+sales)"
_RECV_TARGETS = (
    r"(?:trade\s+receivables?|accounts\s+receivable|net\s+accounts\s+receivable|"
    r"total\s+trade\s+receivables?)"
)

_REVENUE_CONCENTRATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # 1) Customer-subject + verb + X% of revenue
    ("customer-subject + X% of revenue",
     re.compile(
         _CUSTOMER_SUBJECTS +
         r"\s+(?:accounted\s+for|represented|contributed|comprised|generated|were|was)\s+"
         r"(?:approximately\s+)?(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+"
         r"(?:our\s+|the\s+|total\s+|net\s+|its\s+)*" + _REVENUE_TARGETS,
         re.I,
     )),
    # 2) Top-N customers
    ("top-N customers + X% of revenue",
     re.compile(
         r"(?:top|our)\s+(\d+|two|three|four|five|ten)\s+customers?\s+"
         r"(?:accounted\s+for|represented|contributed)\s+"
         r"(?:approximately\s+)?(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+"
         r"(?:our\s+|the\s+|total\s+|net\s+)*" + _REVENUE_TARGETS,
         re.I,
     )),
    # 3) Quoted name / "Customer A" + X% of revenue
    ("named-quoted customer + X% of revenue",
     re.compile(
         r"(?:[\"“”][\w\s\.,&\-]{2,40}[\"“”]|customer\s+[A-Z](?:\s+|\W))"
         r"(?:\s+\w+){0,4}?\s+"
         r"(?:accounted\s+for|represented|contributed)\s+"
         r"(?:approximately\s+)?(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+"
         r"(?:our\s+|the\s+|total\s+|net\s+)*" + _REVENUE_TARGETS,
         re.I,
     )),
    # 4) [Named entity] accounted for X% of revenue (customer-context REQUIRED
    #    by run_pattern_set — see _has_customer_context filter)
    ("named-entity + X% of revenue (customer-context required)",
     re.compile(
         r"\b"
         r"(?!(?:[A-Z]\w*\s+){0,3}"
         r"(?:segment|segments|division|divisions|business\s+line|business\s+lines|"
         r"business\s+unit|business\s+segment|product\s+line|product\s+lines|"
         r"category|categories|geography|geographies|region|regions|"
         r"footprint|channel|channels|store|stores|platform|app|"
         r"states|country|countries|economies))"
         r"([A-Z][\w]{2,}(?:\s+[\w\.,&\-]+){0,2})\s+"
         r"accounted\s+for\s+(?:approximately\s+)?(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+"
         r"(?:our\s+|total\s+|net\s+)*" + _REVENUE_TARGETS,
         re.I,
     )),
    # 5) Two named customers sharing one revenue target: "Inox accounted for
    #    15% and Fuji Bridex accounted for 10% of our total revenues". Pattern 4
    #    binds _REVENUE_TARGETS to the second figure only, dropping the larger.
    ("two named entities sharing one revenue target (customer-context required)",
     re.compile(
         r"([A-Z][\w]{2,}(?:\s+[\w\.,&\-]+){0,2})\s+accounted\s+for\s+"
         r"(?:approximately\s+)?(\d{1,3}(?:\.\d+)?)\s*%\s+and\s+"
         r"[A-Z][\w]{2,}(?:\s+[\w\.,&\-]+){0,2}\s+accounted\s+for\s+"
         r"(?:approximately\s+)?\d{1,3}(?:\.\d+)?\s*%\s+of\s+"
         r"(?:our\s+|the\s+|total\s+|net\s+)*" + _REVENUE_TARGETS,
         re.I,
     )),
]

# Patterns permissive enough to need a 'customer' keyword within ±300 chars.
# Derived by name, not position: `len(...) - 1` silently moves the requirement
# onto whatever pattern is appended last.
_CONTEXT_REQUIRED_NAMES = frozenset(
    {
        "named-entity + X% of revenue (customer-context required)",
        "two named entities sharing one revenue target (customer-context required)",
    }
)
_CONTEXT_REQUIRED_IDX = {
    i for i, (name, _) in enumerate(_REVENUE_CONCENTRATION_PATTERNS)
    if name in _CONTEXT_REQUIRED_NAMES
}

_RECEIVABLES_CONCENTRATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("customer-subject + X% of receivables",
     re.compile(
         _CUSTOMER_SUBJECTS +
         r"\s+(?:accounted\s+for|represented|contributed)\s+"
         r"(?:approximately\s+)?(\d{1,3}(?:\.\d+)?)\s*%\s+of\s+"
         r"(?:our\s+|the\s+|total\s+|net\s+)*" + _RECV_TARGETS,
         re.I,
     )),
    ("one customer 10%+ receivables (Apple-style two-step)",
     re.compile(
         r"one\s+customer\s+(?:that\s+)?(?:represented|accounted\s+for)\s+"
         r"10\s*%\s+or\s+more\s+of\s+(?:our\s+|the\s+|total\s+|net\s+)*" +
         _RECV_TARGETS +
         r"[\s\S]{0,80}?(?:accounted\s+for|which\s+(?:was|represented))\s+"
         r"(?:approximately\s+)?(\d{1,3}(?:\.\d+)?)\s*%",
         re.I,
     )),
    ("[carrier/distributor group] X% of receivables",
     re.compile(
         r"(?:third-party\s+(?:cellular\s+network\s+)?carriers|distributors)\s+"
         r"accounted\s+for\s+(\d{1,3}(?:\.\d+)?)\s*%(?:\s+and\s+(\d{1,3}(?:\.\d+)?)\s*%)?\s+"
         r"of\s+(?:our\s+|the\s+|total\s+)*" + _RECV_TARGETS,
         re.I,
     )),
]

# Threshold is captured, not literal: Reg S-K Item 101(c) mandates disclosure at
# 10%, but issuers volunteer stronger statements at lower thresholds (FAST: 5%).
# _run_negative_set discards captures above _NEGATIVE_MAX_THRESHOLD_PCT — "no
# customer over 50%" is not evidence of diversification.
_NEG_THRESHOLD = r"(\d{1,2}(?:\.\d+)?)"
_NEG_REVENUE_TARGETS = (
    r"(?:our\s+|the\s+|its\s+|total\s+|net\s+|consolidated\s+|annual\s+)*"
    r"(?:revenues?|sales|net\s+sales|billings)"
)
_NEGATIVE_MAX_THRESHOLD_PCT = 10.0

_NEGATIVE_DISCLOSURE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("no [single|individual] customer >=N%",
     re.compile(
         r"no\s+(?:single|individual|one)?\s*customer\s+"
         r"(?:account(?:s|ed)?|represent(?:s|ed)?)\s+"
         r"(?:for\s+)?(?:more\s+than\s+|over\s+)?" + _NEG_THRESHOLD +
         r"\s*%(?:\s+or\s+more)?",
         re.I,
     )),
    ("no other customer >=N%",
     re.compile(
         r"no\s+other\s+customer\s+account(?:s|ed)?\s+for\s+"
         r"(?:more\s+than\s+|over\s+)?" + _NEG_THRESHOLD + r"\s*%(?:\s+or\s+more)?",
         re.I,
     )),
    ("none of our customers (Apple-style)",
     re.compile(
         r"(?:no\s+(?:single\s+)?customer|none\s+of\s+our\s+customers)\s+"
         r"(?:accounted\s+for|represented)\s+" + _NEG_THRESHOLD +
         r"\s*%\s+or\s+more\s+of\s+" + _NEG_REVENUE_TARGETS,
         re.I,
     )),
    ("no sales to [a single|an individual] customer >=N% (Microsoft-style)",
     re.compile(
         r"no\s+sales\s+to\s+(?:a\s+single\s+|an\s+individual\s+|one\s+|any\s+)"
         r"(?:individual\s+)?customer(?:\s+or\s+\w+)?\s+"
         r"(?:[\w\s]+\s+)?(?:accounted\s+for|represented)\s+"
         r"(?:more\s+than\s+|over\s+)?" + _NEG_THRESHOLD + r"\s*%(?:\s+or\s+more)?",
         re.I,
     )),
]


def parse_customer_concentration(text: str) -> CustomerSignals:
    """ADR-018 D4 — extract revenue + receivables concentration with 3-state.

    Run on the concatenation of TenK section accessors [Item 1, 1A, 7, 8].
    Returns CustomerSignals with both `concentration_pct` (revenue) and
    `receivables_concentration_pct` populated independently, plus a 3-state
    `state` value.

    Priority: revenue > receivables > negative-disclosure absence > silence.
    """
    # Blank input means the sections were unreadable, not that the issuer is
    # diversified — never let it reach the not_disclosed branch.
    if not text or not text.strip():
        return CustomerSignals()

    rev_hits = _run_pattern_set(
        text, _REVENUE_CONCENTRATION_PATTERNS,
        require_customer_context_idx=_CONTEXT_REQUIRED_IDX,
    )
    rec_hits = _run_pattern_set(text, _RECEIVABLES_CONCENTRATION_PATTERNS)
    neg_hits = _run_negative_set(text)

    rev_max = max((h[2] for h in rev_hits), default=None)
    rec_max = max((h[2] for h in rec_hits), default=None)

    if rev_hits:
        return CustomerSignals(
            concentration_pct=rev_max,
            receivables_concentration_pct=rec_max,
            relationship_years=parse_relationship_years(text),
            extraction_method="regex",
            state="disclosed_exact",
        )
    if rec_hits:
        return CustomerSignals(
            concentration_pct=None,
            receivables_concentration_pct=rec_max,
            relationship_years=parse_relationship_years(text),
            extraction_method="regex",
            state="disclosed_exact",   # disclosed (receivables-only) — caller distinguishes via state + columns
        )
    if neg_hits:
        return CustomerSignals(
            concentration_pct=None,
            receivables_concentration_pct=None,
            relationship_years=parse_relationship_years(text),
            extraction_method="negative_phrase",
            state="not_disclosed",
        )
    return CustomerSignals(state="not_disclosed")


_PCT_SUFFIX = re.compile(r"\s*%")


def _first_percent_group(text: str, m: re.Match[str]) -> float | None:
    """Earliest captured group that is genuinely a percentage.

    Groups are tested by what follows them in `text`, not by position: the
    top-N patterns lead with a customer *count* group, while the carrier
    receivables pattern captures (current_pct, prior_pct). Taking the last
    numeric group would return the prior-year figure for the latter.
    """
    for idx in range(1, (m.lastindex or 0) + 1):
        raw = m.group(idx)
        if not raw or not raw.replace(".", "").replace(",", "").isdigit():
            continue
        if not _PCT_SUFFIX.match(text, m.end(idx)):
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def _run_pattern_set(
    text: str,
    patterns: list[tuple[str, re.Pattern[str]]],
    require_customer_context_idx: set[int] | None = None,
) -> list[tuple[str, str, float]]:
    """Run a pattern set over `text`, returning (name, snippet, value_pct).

    Patterns indexed in `require_customer_context_idx` are filtered to
    require the literal word 'customer' within ±300 chars of the match.
    Used to suppress segment/division/product-line false positives in the
    permissive [Named entity] pattern.
    """
    out: list[tuple[str, str, float]] = []
    for idx, (name, pat) in enumerate(patterns):
        for m in pat.finditer(text):
            val = _first_percent_group(text, m)
            if val is None or not (5.0 <= val <= 100.0):
                continue
            if require_customer_context_idx and idx in require_customer_context_idx:
                window = text[max(0, m.start() - 300): min(len(text), m.end() + 300)]
                if "customer" not in window.lower():
                    continue
            start = max(0, m.start() - 100)
            end = min(len(text), m.end() + 150)
            snippet = re.sub(r"\s+", " ", text[start:end].strip())
            out.append((name, snippet, val))
    return out


def _run_negative_set(text: str) -> list[tuple[str, str]]:
    """Explicit no-concentration disclosures, at or below the Reg S-K threshold."""
    out: list[tuple[str, str]] = []
    for name, pat in _NEGATIVE_DISCLOSURE_PATTERNS:
        for m in pat.finditer(text):
            threshold = m.group(1) if m.groups() else None
            if threshold is not None:
                try:
                    if float(threshold) > _NEGATIVE_MAX_THRESHOLD_PCT:
                        continue
                except ValueError:
                    continue
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 150)
            snippet = re.sub(r"\s+", " ", text[start:end].strip())
            out.append((name, snippet))
    return out


# ── Patent disclosures (5k-6 partial) ─────────────────────────────────────


@dataclass
class PatentSignals:
    """Patent count from 10-K text disclosure.

    The full Hirshleifer-Hsu-Li (2013, JFE ★★★) Innovative Efficiency
    signal requires forward citations from USPTO data. PatentsView (the
    free no-key API) was decommissioned 2024; api.uspto.gov requires a
    developer-portal API key that's a user-side action. This 10-K text
    fallback captures only the absolute patent count when companies
    disclose it in narrative. Useful for tech / biotech tickers that
    routinely brag about portfolio size; silent for the rest.

    Once USPTO_API_KEY is configured (see 5k-6b), the data layer can
    backfill `patent_count` + `patent_citations_received` via the
    authenticated USPTO API — at which point F3 picks up the full HHL
    signal automatically.
    """
    patent_count: int | None = None
    extraction_method: str = "none"          # 'regex' | 'none'
    state: str = "none"


# Captures phrases like:
#   "we own approximately 25,000 issued patents"
#   "our patent portfolio of 1,200 patents"
#   "as of December 31, 2024, we held 850 issued U.S. patents"
#   "approximately 12,500 issued and pending patents worldwide"
# Excludes vague qualitative mentions ("we have many patents") and
# non-portfolio numbers (litigation counts).
_PATENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:approximately|approx\.?|over|more\s+than|nearly|"
        r"in\s+excess\s+of|~|hold\s+of?|own(?:ed)?|portfolio\s+of|"
        r"issued|granted)?\s*"
        r"(\d{1,3}(?:,\d{3})+|\d{2,6})"
        r"\s+(?:issued\s+(?:and\s+pending\s+)?(?:U\.?S\.?\s+)?patents"
        r"|U\.?S\.?\s+and\s+foreign\s+patents"
        r"|patent\s+(?:applications|portfolio|grants?)"
        r"|patents(?:\s+(?:and\s+patent\s+applications|worldwide|globally|"
        r"in\s+force|covering|across))?)",
        re.I,
    ),
]

# Sanity range. 1 patent is plausible for biotech; cap 200,000 (IBM-class).
_PATENT_VALID_LO, _PATENT_VALID_HI = 1, 200_000


def parse_patent_count(text: str) -> PatentSignals:
    """Extract self-reported patent count from 10-K narrative.

    Returns ``PatentSignals(state='not_disclosed')`` when nothing
    validatable matches. The first valid hit wins; subsequent mentions
    in the same filing usually reference the same number.
    """
    if not text:
        return PatentSignals(state="not_disclosed")

    relevant = _find_relevant_paragraphs(
        text, ["patent", "intellectual property", "ip portfolio"],
    )
    if not relevant:
        return PatentSignals(state="not_disclosed")

    for para in relevant:
        for pattern in _PATENT_PATTERNS:
            for m in pattern.finditer(para):
                raw = m.group(1).replace(",", "")
                try:
                    val = int(raw)
                except ValueError:
                    continue
                if _PATENT_VALID_LO <= val <= _PATENT_VALID_HI:
                    return PatentSignals(
                        patent_count=val,
                        extraction_method="regex",
                        state="disclosed_exact",
                    )
    return PatentSignals(state="not_disclosed")


# ── ARR metrics (Cloud + Total) — ADR-026 / Phase 5Q-5 ───────────────────


@dataclass
class ARRSignals:
    """SaaS ARR (Annual Recurring Revenue) metrics from MD&A free text.

    Cloud ARR is the canonical forward-looking SaaS revenue metric.
    Total ARR includes both SaaS and on-premise. Disclosed in MD&A
    narrative quarterly; not an XBRL fact, so we regex it.
    """
    cloud_arr_usd: float | None = None              # Cloud SaaS ARR in USD
    cloud_arr_growth_yoy_pct: float | None = None   # YoY % growth
    total_arr_usd: float | None = None              # Total ARR (SaaS + on-prem)
    total_arr_growth_yoy_pct: float | None = None
    extraction_method: str = "none"
    state: str = "none"      # disclosed_exact | parser_uncertain | not_disclosed


# Cloud ARR — most specific, captured first so it wins when both present.
# Phrasings observed across SaaS 10-Q/10-K corpus:
#   "Cloud ARR was $459.3 million... an increase of 31%"
#   "Cloud ARR grew to $459 million, up 31% YoY"
#   "Cloud ARR reached $459M"
_CLOUD_ARR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\bcloud\s+ARR\b[\s\S]{0,40}?"
        r"(?:was|reached|grew\s+to|of|equaled|stood\s+at|is)"
        r"\s*\$?\s*(\d+(?:[,.]\d+)?)"
        r"\s*(million|billion|m\b|bn\b|b\b)",
        re.I,
    ),
]
_TOTAL_ARR_PATTERNS: list[re.Pattern[str]] = [
    # "Total ARR was $X million" or just "ARR was $X million" (when not Cloud-prefixed)
    re.compile(
        r"\b(?:total\s+)?ARR\b[\s\S]{0,40}?"
        r"(?:was|reached|grew\s+to|of|equaled|stood\s+at|is)"
        r"\s*\$?\s*(\d+(?:[,.]\d+)?)"
        r"\s*(million|billion|m\b|bn\b|b\b)",
        re.I,
    ),
]
# Growth-rate co-located with ARR mention. Looks within ~200 chars after
# the ARR value: "an increase of 31%", "up 31%", "grew 31%".
_ARR_GROWTH_PATTERN = re.compile(
    r"(?:increase\s+of|up|grew|grew\s+by|growth\s+of)\s+(\d+(?:\.\d+)?)\s*%",
    re.I,
)

_ARR_VALUE_VALID_LO_USD = 1e6              # $1M floor — anything smaller is noise
_ARR_VALUE_VALID_HI_USD = 100e9            # $100B ceiling
_ARR_GROWTH_VALID_LO_PCT = -50.0
_ARR_GROWTH_VALID_HI_PCT = 500.0


def _normalise_arr_value(raw_num: str, unit: str) -> float | None:
    """Convert '459.3' + 'million' → 459_300_000. Returns None on bad input."""
    cleaned = raw_num.replace(",", "")
    try:
        val = float(cleaned)
    except ValueError:
        return None
    unit_low = unit.lower().strip(" .")
    if unit_low in ("million", "m"):
        val *= 1e6
    elif unit_low in ("billion", "bn", "b"):
        val *= 1e9
    if val < _ARR_VALUE_VALID_LO_USD or val > _ARR_VALUE_VALID_HI_USD:
        return None
    return val


def _growth_near(text: str, anchor_idx: int, window: int = 240) -> float | None:
    """Look for a growth-rate mention within ``window`` chars after ``anchor_idx``.

    Used to attribute a "...an increase of 31%" growth-rate phrase to the
    ARR value that immediately precedes it. Without proximity gating,
    growth phrases from unrelated paragraphs would mis-attribute.
    """
    snippet = text[anchor_idx:anchor_idx + window]
    m = _ARR_GROWTH_PATTERN.search(snippet)
    if not m:
        return None
    try:
        pct = float(m.group(1))
    except ValueError:
        return None
    if pct < _ARR_GROWTH_VALID_LO_PCT or pct > _ARR_GROWTH_VALID_HI_PCT:
        return None
    return pct


def parse_arr_metrics(text: str) -> ARRSignals:
    """Extract Cloud ARR + Total ARR + YoY growth from MD&A free-text.

    Cloud ARR is captured first (more specific phrasing). If a Total-ARR
    pattern matches a position that overlaps with a Cloud-ARR hit, it's
    skipped (avoids double-counting). Growth rates are attributed by
    proximity — the percent within ~240 chars after the value.
    """
    if not text:
        return ARRSignals(state="not_disclosed")

    # Keywords passed lowercase — _find_relevant_paragraphs lowercases the
    # paragraph for comparison but not the keywords.
    relevant = _find_relevant_paragraphs(
        text,
        ["arr", "annual recurring revenue", "cloud arr"],
        max_chars=120_000,
    )
    if not relevant:
        return ARRSignals(state="not_disclosed")

    cloud_value: float | None = None
    cloud_growth: float | None = None
    total_value: float | None = None
    total_growth: float | None = None
    saw_phrase = False
    matched_positions: list[tuple[int, int, str]] = []   # (start, end, original_text)

    for para in relevant:
        # Cloud ARR first
        if cloud_value is None:
            for pattern in _CLOUD_ARR_PATTERNS:
                for m in pattern.finditer(para):
                    saw_phrase = True
                    val = _normalise_arr_value(m.group(1), m.group(2))
                    if val is None:
                        continue
                    cloud_value = val
                    cloud_growth = _growth_near(para, m.end())
                    matched_positions.append((m.start(), m.end(), m.group(0)))
                    break
                if cloud_value is not None:
                    break
        # Total ARR (skip if it overlaps a Cloud-ARR match)
        if total_value is None:
            for pattern in _TOTAL_ARR_PATTERNS:
                for m in pattern.finditer(para):
                    saw_phrase = True
                    # Skip overlapping matches with the Cloud-ARR hit
                    overlaps = any(
                        m.start() < end and m.end() > start
                        for start, end, _ in matched_positions
                    )
                    if overlaps:
                        continue
                    # Also skip "Cloud ARR" prefixed mentions (the Cloud pattern
                    # didn't match — likely because Cloud isn't on the
                    # canonical anchor list — but we still want to dodge it)
                    pre = para[max(0, m.start() - 10):m.start()].lower()
                    if "cloud" in pre:
                        continue
                    val = _normalise_arr_value(m.group(1), m.group(2))
                    if val is None:
                        continue
                    total_value = val
                    total_growth = _growth_near(para, m.end())
                    break
                if total_value is not None:
                    break
        if cloud_value is not None and total_value is not None:
            break

    if cloud_value is not None or total_value is not None:
        return ARRSignals(
            cloud_arr_usd=cloud_value,
            cloud_arr_growth_yoy_pct=cloud_growth,
            total_arr_usd=total_value,
            total_arr_growth_yoy_pct=total_growth,
            extraction_method="regex",
            state="disclosed_exact",
        )
    if saw_phrase:
        return ARRSignals(state="parser_uncertain")
    return ARRSignals(state="not_disclosed")


# ── Retention metrics (NRR / GRR) — Phase 5k-7 ────────────────────────────


@dataclass
class RetentionSignals:
    """SaaS retention metrics extracted from 10-K MD&A free text.

    NRR (Net Revenue Retention) and GRR (Gross Revenue Retention) are the
    canonical SaaS diagnostic — F6 PROJECT_SPEC weights them at 2/10. No
    XBRL tag exists; companies disclose in MD&A narrative when they choose
    to. Hit rate target: 30-40% of SaaS tickers (companies that explicitly
    quantify in 10-K, vs only mention qualitatively or omit entirely).
    """
    nrr_pct: float | None = None             # net dollar retention as %
    grr_pct: float | None = None             # gross retention as %
    extraction_method: str = "none"          # 'regex' | 'none'
    # state semantics:
    #   'disclosed_exact' — at least one metric extracted with confidence
    #   'parser_uncertain' — phrase matched but value couldn't be tied
    #   'not_disclosed'   — no retention phrasing found (genuine omission)
    state: str = "none"


# Phrasing to match. Each pattern captures the value group on the same
# line/short window. Word boundaries on metric phrase prevent matches
# inside larger phrases. Value range gating happens after extraction.
# Required verb prefix between metric name and value. Mandatory (no `?`)
# to avoid false positives from calculation explanations like "renewal
# rate by subtracting attrition from 100%" — without the verb gate, the
# 100% there matches before the real "was 98%" disclosure.
_VERB_PREFIX_NRR = (
    r"(?:of|was|is|equal(?:ed)?\s+to|=|:|reached|approximately|"
    r"approx\.?|~|stood\s+at|expanded\s+to)"
)
_VERB_PREFIX_GRR = (
    r"(?:of|was|is|equal(?:ed)?\s+to|=|:|reached|approximately|"
    r"approx\.?|~|stood\s+at|exceeded|over)"
)

_NRR_PATTERNS: list[re.Pattern[str]] = [
    # "Net Revenue Retention rate of 110%" / "net dollar retention was 113%"
    re.compile(
        r"\b(?:net\s+(?:revenue|dollar)\s+retention(?:\s+rate)?"
        r"|dollar[-\s]?based\s+net\s+(?:retention|expansion)(?:\s+rate)?"
        r"|\bnrr\b|\bndrr\b|net\s+expansion\s+rate)"
        r"[\s\S]{0,40}?" + _VERB_PREFIX_NRR + r"\s*(\d{2,3}(?:\.\d{1,2})?)\s*%",
        re.I,
    ),
    # Decimal x form: "NRR of 1.10x" or "net retention of 1.15"
    re.compile(
        r"\b(?:net\s+(?:revenue|dollar)\s+retention(?:\s+rate)?|nrr)"
        r"[\s\S]{0,40}?" + _VERB_PREFIX_NRR + r"\s*(1\.\d{1,2})\s*x?",
        re.I,
    ),
]

_GRR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:gross\s+(?:revenue|dollar)?\s*retention(?:\s+rate)?"
        r"|\bgrr\b"
        # Renewal rate (mathematically equivalent to GRR per ServiceNow:
        # "renewal rate = 100% - attrition rate"). Phrasing common in
        # enterprise SaaS 10-Ks where "retention" terminology is avoided.
        r"|renewal\s+rate)"
        r"[\s\S]{0,40}?" + _VERB_PREFIX_GRR + r"\s*(\d{2,3}(?:\.\d{1,2})?)\s*%",
        re.I,
    ),
]

# Negative phrases — when these match within ~30 chars of a retention
# phrase, suppress extraction (avoid false-positive on "we do not disclose"
# or "we do not measure NRR").
_RETENTION_NEGATIVE = re.compile(
    r"\b(?:do\s+not|does\s+not|don['']?t|doesn['']?t|will\s+not)\s+"
    r"(?:disclose|measure|report|track|quantify|publish)",
    re.I,
)

# Sanity-check ranges. SaaS NRR is typically 80-160% (above 200% would be
# either parser error or a TAM/category-defining outlier we want to flag,
# not silently accept). GRR is typically 70-110% (can't exceed 100% by
# definition but reported values sometimes round above due to one-off true-ups).
_NRR_VALID_LO, _NRR_VALID_HI = 60.0, 200.0
_GRR_VALID_LO, _GRR_VALID_HI = 50.0, 110.0


def parse_retention_metrics(text: str) -> RetentionSignals:
    """Extract NRR / GRR from MD&A free-text. Zero LLM, deterministic regex.

    Strategy:
      1. Restrict search to paragraphs containing 'retention' or NRR/GRR
         tokens to keep false-positive rate low (full 10-K is ~250kb).
      2. For each match, check the preceding ~80 chars for a negation
         phrase ("do not disclose" / "do not measure"). Suppress if found.
      3. Validate value falls in the expected SaaS range. Reject outliers.
      4. Return the FIRST valid hit per metric — multiple disclosures in
         the same filing usually quote the same number across MD&A and
         risk factors; first stable match wins.

    Returns ``RetentionSignals(state='not_disclosed')`` when nothing valid
    matches — the diversified-default treatment from F6 docstring (3-state
    semantics align with customer_concentration).
    """
    if not text:
        return RetentionSignals(state="not_disclosed")

    # Bump max_chars from default 8k to 80k: ServiceNow MD&A is ~55k chars
    # and the "renewal rate was 98%" disclosure sits well past 8k. The
    # broader Item 1A risk-factor pre-amble eats the smaller cap.
    relevant = _find_relevant_paragraphs(
        text,
        ["retention", "nrr", "ndrr", "grr", "net dollar", "dollar-based",
         "expansion rate", "renewal rate"],
        max_chars=80_000,
    )
    if not relevant:
        return RetentionSignals(state="not_disclosed")

    nrr_value: float | None = None
    grr_value: float | None = None
    saw_phrase = False

    for para in relevant:
        # Cheap negation check on the whole paragraph — if it explicitly
        # denies disclosure, skip extraction for this para entirely.
        if _RETENTION_NEGATIVE.search(para):
            saw_phrase = True
            continue

        if nrr_value is None:
            for pattern in _NRR_PATTERNS:
                m = pattern.search(para)
                if not m:
                    continue
                saw_phrase = True
                raw = m.group(1)
                try:
                    val = float(raw)
                except ValueError:
                    continue
                # Decimal-x form normalises to %  (1.15 → 115%)
                if val < 5:
                    val *= 100
                if _NRR_VALID_LO <= val <= _NRR_VALID_HI:
                    nrr_value = round(val, 2)
                    break

        if grr_value is None:
            for pattern in _GRR_PATTERNS:
                m = pattern.search(para)
                if not m:
                    continue
                saw_phrase = True
                raw = m.group(1)
                try:
                    val = float(raw)
                except ValueError:
                    continue
                if _GRR_VALID_LO <= val <= _GRR_VALID_HI:
                    grr_value = round(val, 2)
                    break

        if nrr_value is not None and grr_value is not None:
            break

    if nrr_value is not None or grr_value is not None:
        return RetentionSignals(
            nrr_pct=nrr_value,
            grr_pct=grr_value,
            extraction_method="regex",
            state="disclosed_exact",
        )
    if saw_phrase:
        # Phrase matched but no validatable value — could be qualitative
        # mention or value out of range. Surface as parser_uncertain so
        # downstream knows to investigate, not silently treat as absence.
        return RetentionSignals(state="parser_uncertain")
    return RetentionSignals(state="not_disclosed")


# ── Relationship duration (10-K plain text) ───────────────────────────────

_YEAR_SINCE_PATTERN = re.compile(r"since\s+(\d{4})", re.I)
_YEAR_COUNT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(\d{1,2})-year\s+(?:relationship|partnership|agreement|contract|history)", re.I),
    re.compile(r"(?:over|past|more\s+than)\s+(?:the\s+)?(?:past\s+)?(\d{1,2})\s+years?", re.I),
    re.compile(r"for\s+(?:more\s+than\s+|over\s+)?(\d{1,2})\s+years?", re.I),
    re.compile(r"(\d{1,2})\s+years?\s+of\s+(?:service|relationship|partnership)", re.I),
]


def parse_relationship_years(text: str) -> float | None:
    """Extract customer relationship duration in years from 10-K text."""
    relevant = _find_relevant_paragraphs(
        text, ["customer", "relationship", "partnership", "since", "year"]
    )
    for para in relevant:
        # "since 2008" — most reliable; compute elapsed years
        for m in _YEAR_SINCE_PATTERN.finditer(para):
            year = int(m.group(1))
            if 1985 <= year <= _CURRENT_YEAR:
                elapsed = _CURRENT_YEAR - year
                if 1 <= elapsed <= 50:
                    return float(elapsed)
        # Explicit year count patterns
        for pattern in _YEAR_COUNT_PATTERNS:
            for m in pattern.finditer(para):
                try:
                    val = float(m.group(1))
                    if 1.0 <= val <= 50.0:
                        return val
                except (ValueError, IndexError):
                    pass
    return None


# ── Beneficial ownership table (DEF 14A HTML) ─────────────────────────────


def parse_proxy_ownership(html: str, ceo_name_hint: str | None = None) -> ProxyOwnership:
    """
    Parse CEO ownership % from DEF 14A HTML.

    Finds the "Security Ownership of ... Management" section, locates the
    beneficial ownership table, and extracts the CEO's row.

    `ceo_name_hint` helps match the correct row when the CEO title is not
    in the same table cell as the name (common in proxy formatting).
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
    except ImportError:
        logger.warning("beautifulsoup4 not installed — proxy HTML parsing skipped")
        return ProxyOwnership()

    try:
        soup = BeautifulSoup(html, "html.parser")
        return _parse_ownership_table(soup, ceo_name_hint)
    except Exception as exc:
        logger.debug("DEF 14A parse error: %s", exc)
        return ProxyOwnership()


def _parse_ownership_table(soup: object, ceo_name_hint: str | None) -> ProxyOwnership:
    """Find the beneficial-ownership table in a DEF 14A and read CEO equity %.

    Discovery strategy (v2, 2026-05-15 — three bug fixes from HIMS smoke test):

      Bug #1 (table discovery) — the prior implementation walked 24 tables
      forward from each "Security Ownership" heading; for HIMS the real
      ownership table is at global index 53, far past that limit. Now we
      scan ALL tables in the document and rank by header-signature
      strength: a table with "Beneficial Owner" + "Number of Shares" +
      "%" columns is the ownership table regardless of position.

      Bug #2 (regex too permissive) — the prior regex
      `r"(\\d{1,3}(?:\\.\\d+)?)\\s*%?"` made the % literal optional, which
      meant the parser accepted "625" out of "$625,000" in a salary
      column. Now the regex REQUIRES `%` to anchor the match — anything
      else gets ignored.

      Bug #3 (multi-class voting column wrong) — for dual-class issuers
      (HIMS: Class A common + Class V super-voting), the rightmost
      column is typically "% of Total Voting Power" — NOT economic
      equity. The prior right-to-left scan grabbed Dudum's 87.73% voting
      power and persisted it as `ceo_equity_pct`, materially overstating
      his economic stake. Now multi-class detection routes to the
      "% of Class A" column (or first non-voting-power % column), and
      multi_class_detected is set on the result.
    """
    result = ProxyOwnership()

    last_name_hint = (
        (ceo_name_hint or "").split()[-1].lower() if ceo_name_hint else None
    )
    ceo_keywords = {"chief executive", "ceo", "president and ceo", "chairman and ceo"}

    # ── Bug #1 fix: signature-based table discovery (scan ALL tables) ────
    # Score every table in the document by header-signature strength.
    # Top scorer is the beneficial-ownership table.
    candidates: list[tuple[int, Any]] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        full_text = table.get_text(separator=" ", strip=True).lower()
        score = 0
        # Strong ownership-table signals (must have at least one)
        if "beneficial owner" in full_text:
            score += 5
        if "beneficially own" in full_text:
            score += 3
        if "number of shares" in full_text or "shares beneficially" in full_text:
            score += 3
        if "percent of class" in full_text or "% of class" in full_text:
            score += 3
        # Negative signals — these tables LOOK like ownership but aren't
        if "base salary" in full_text or "target bonus" in full_text:
            score -= 10
        if "compensation" in full_text and "ownership" not in full_text:
            score -= 5
        if "target annual incentive" in full_text:
            score -= 10
        if "merit increase" in full_text:
            score -= 10
        # Must contain percentage data
        if "%" not in full_text:
            score -= 3
        # CEO presence is a tiebreaker
        if last_name_hint and last_name_hint in full_text:
            score += 2
        if any(kw in full_text for kw in ceo_keywords):
            score += 1
        if score >= 5:
            candidates.append((score, table))

    # Sort descending by score; iterate in that order
    candidates.sort(key=lambda t: -t[0])

    for _score, table in candidates:
        rows = table.find_all("tr")

        # Collect all data rows (skip header rows — identified by lacking any
        # cell that looks like a share count or %, or rows with all-bold or
        # ≤1 non-empty cell)
        def _row_cells(row):
            return [td.get_text(separator=" ", strip=True)
                    for td in row.find_all(["td", "th"])]
        all_rows_cells = [_row_cells(r) for r in rows]

        # Find the CEO row first — needed before we can exclude it from
        # the consensus-column-typing pass
        ceo_row_cells = None
        ceo_row_idx = None
        for ridx, cells in enumerate(all_rows_cells):
            if len(cells) < 2:
                continue
            combined = " ".join(cells).lower()
            is_ceo_row = any(kw in combined for kw in ceo_keywords)
            if not is_ceo_row and last_name_hint:
                is_ceo_row = last_name_hint in combined
            if is_ceo_row:
                ceo_row_cells = cells
                ceo_row_idx = ridx
                break

        if ceo_row_cells is None:
            continue

        # ── Data-row-shape consensus typing (replaces fragile header
        # colspan/rowspan tracking) ─────────────────────────────────────
        #
        # Header position-mapping fails because PATH uses `colspan=2` and
        # HIMS uses `colspan=3` on header cells while data rows use
        # `colspan=1` cells, breaking cell-index alignment between header
        # and data rows. The robust fix is to LEARN column types from
        # actual data rows: across all data rows that share the CEO's
        # cell count, count what each column position contains:
        #   - "pct"          — cell matches r'\d+(?:\.\d+)?\s*%'
        #   - "share_count"  — digits-with-commas, ≥1000, no `%`
        #   - "redaction"    — just `*` or `(*)`
        #   - "dash"         — `—`, `-`, or empty
        #   - "name"         — non-numeric text
        # For each position, take the dominant type as the column's role.
        # Then route by: first pct after first share_count is economic
        # equity; trailing pct (if pct_count > share_count) is voting.

        n_cols = len(ceo_row_cells)
        from collections import Counter as _Counter
        col_type_votes: list[_Counter] = [_Counter() for _ in range(n_cols)]
        # Include the CEO row in the typing pass — for issuers like HIMS
        # where the founder is the sole holder of the super-voting class
        # (Class V), only their row carries non-dash values in those
        # column positions. Excluding the CEO would misclassify those
        # columns as pure-dash padding and lose the multi-class signal.
        for ridx, cells in enumerate(all_rows_cells):
            if len(cells) != n_cols:
                continue
            for ci, cell in enumerate(cells):
                cell_stripped = cell.strip()
                if not cell_stripped or cell_stripped in ("—", "-", "–"):
                    col_type_votes[ci]["dash"] += 1
                elif cell_stripped in ("*", "(*)", "**"):
                    col_type_votes[ci]["redaction"] += 1
                elif re.search(r"\d+(?:\.\d+)?\s*%", cell_stripped):
                    col_type_votes[ci]["pct"] += 1
                elif re.fullmatch(r"[\d,]+(?:\.\d+)?", cell_stripped) and \
                        int(re.sub(r"[^\d]", "", cell_stripped) or "0") >= 1000:
                    col_type_votes[ci]["share_count"] += 1
                elif re.search(r"[A-Za-z]", cell_stripped):
                    col_type_votes[ci]["name"] += 1
                else:
                    col_type_votes[ci]["other"] += 1

        # Hybrid majority-then-presence column typing.
        #
        # Failure modes the rules guard against:
        #   - Pure majority — misclassifies HIMS Class V columns as
        #     "dash" because only the founder has values (1 share_count
        #     row, many dash rows)
        #   - Pure presence — misclassifies MRVL col 1 as "pct" because
        #     the section-header row "5% Stockholders:" matches the
        #     pct regex on "5%" (1 stray pct vote against 18 name votes)
        #
        # Hybrid rule:
        #   1. If a single category has CLEAR majority (> 2x next),
        #      use it (catches MRVL col 1 "name" dominant)
        #   2. Else, fall back to presence-based rules with type-priority
        #      to handle minority signals (catches HIMS Class V)
        col_types: dict[int, str] = {}
        for ci, votes in enumerate(col_type_votes):
            if not votes:
                continue
            v = lambda k: votes.get(k, 0)  # noqa: E731
            n_share = v("share_count")
            n_pct = v("pct") + v("redaction")
            n_name = v("name")
            n_dash = v("dash")
            n_other = v("other")

            # Step 1: clear majority (≥2x next) wins outright
            sorted_votes = sorted(
                [
                    ("share_count", n_share),
                    ("pct", n_pct),
                    ("name", n_name),
                    ("dash", n_dash + n_other),  # ZWS/other treated as padding
                ],
                key=lambda t: -t[1],
            )
            top_type, top_n = sorted_votes[0]
            second_n = sorted_votes[1][1] if len(sorted_votes) > 1 else 0
            if top_n >= 2 * max(second_n, 1) and top_n >= 2:
                # Clear majority
                if top_type == "dash":
                    # Mostly empty/padding — but may still be a
                    # secondary-class column (HIMS Class V pattern
                    # where only the CEO has values, everyone else is `—`).
                    # Require AT LEAST ONE share_count or pct vote to
                    # promote out of "dash" — pure-ZWS-padding columns
                    # (MRVL pattern) stay as dash.
                    if n_share >= 1 and n_pct == 0:
                        col_types[ci] = "share_count"
                    elif n_pct >= 1 and n_share == 0:
                        col_types[ci] = "pct"
                    else:
                        col_types[ci] = "dash"
                else:
                    col_types[ci] = top_type
                continue

            # Step 2: no clear majority — fall back to presence priority
            # (share_count > pct > name). The adjacent-share_count
            # fallback was removed 2026-05-15 (MRVL regression: it
            # promoted pure-padding cols 7-11 to "pct" when they had
            # no pct evidence at all).
            if n_share > 0 and n_pct == 0:
                col_types[ci] = "share_count"
            elif n_pct > 0 and n_share == 0:
                col_types[ci] = "pct"
            elif n_share > 0 and n_pct > 0:
                col_types[ci] = "share_count" if n_share >= n_pct else "pct"
            elif n_name > 0:
                col_types[ci] = "name"
            else:
                col_types[ci] = "dash"

        pct_cols = sorted(ci for ci, t in col_types.items() if t == "pct")
        share_cols = sorted(ci for ci, t in col_types.items() if t == "share_count")
        is_multi_class = len(share_cols) >= 2

        result.ceo_name = ceo_row_cells[0].strip() or None
        result.extraction_method = "html_table"
        result.multi_class_detected = is_multi_class

        # Determine which %-column is the ECONOMIC equity column
        # (the column we want for ceo_equity_pct)
        economic_col: int | None = None
        if pct_cols:
            if len(pct_cols) == 1:
                economic_col = pct_cols[0]
            elif is_multi_class:
                # Multi-class: economic = first %-col after first share_col
                first_share = share_cols[0]
                candidates_after = [c for c in pct_cols if c > first_share]
                if candidates_after:
                    economic_col = candidates_after[0]
                else:
                    economic_col = pct_cols[0]
            else:
                # Single-class: just take the first %-col
                economic_col = pct_cols[0]

        picked_value: float | None = None
        less_than_one_signal = False

        if economic_col is not None and economic_col < len(ceo_row_cells):
            cell_text = ceo_row_cells[economic_col]
            val = _extract_pct_literal(cell_text)
            if val is not None:
                picked_value = val
            elif "*" in cell_text:
                less_than_one_signal = True
            elif not cell_text.strip() or cell_text.strip() in ("—", "-", "–"):
                # Empty cell at economic-equity position in multi-class
                # context = sub-1% disclosure threshold (HIMS Dudum
                # pattern — % of Class A column was blank)
                if is_multi_class:
                    less_than_one_signal = True

        # Legacy fall-through path retained for cases where data-row
        # consensus failed (rare — usually means the table is too sparse)
        if picked_value is None and not less_than_one_signal:
            # Last-resort fallback when data-row consensus failed: scan
            # the CEO row left-to-right for ANY cell with a %-literal,
            # take the first one. This handles tables with only the CEO
            # row visible (very sparse) or unusual layouts the consensus
            # couldn't read. In multi-class layouts we exclude the
            # rightmost % cell (which is usually voting power).
            ceo_pct_positions = [
                ci for ci, c in enumerate(ceo_row_cells)
                if _extract_pct_literal(c) is not None
            ]
            if ceo_pct_positions:
                # Multi-class voting-power exclusion: if there are >=2
                # %-cells, drop the rightmost (voting power convention)
                if is_multi_class and len(ceo_pct_positions) >= 2:
                    ceo_pct_positions = ceo_pct_positions[:-1]
                if ceo_pct_positions:
                    picked_value = _extract_pct_literal(
                        ceo_row_cells[ceo_pct_positions[0]]
                    )

        # Outcome routing
        if less_than_one_signal:
            # Explicit redaction — economic equity is less than 1%.
            # This is a TRUE finding, not a parser failure. Record as
            # disclosed_exact with the value 0.5 (mid-point of <1% range)
            # AND a state annotation. F5's scoring threshold is 5% so
            # this correctly does NOT trigger founder_aligned regardless.
            result.ceo_equity_pct = 0.5  # under-1% convention
            result.state = "disclosed_exact_under_1pct"
            return result

        if picked_value is None:
            # Couldn't find a usable %-column — record uncertain,
            # do NOT persist a guess.
            result.state = "parser_uncertain"
            return result

        result.ceo_equity_pct = (
            picked_value if picked_value >= 0.1 else picked_value * 100.0
        )
        result.state = "disclosed_exact"
        return result

    return result


_PCT_VALUE_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def _extract_pct_literal(cell_text: str) -> float | None:
    """Extract a percentage value from a cell — REQUIRES the literal `%`
    character to anchor the match. Returns None for cells without an
    explicit percent (skipping share-counts, dollar amounts, footnote
    markers like `*`, etc.).

    Vector 2 of ADR-031 §1.2 parser bugs — this strict-percent
    requirement is what closes the "625 from $625,000" failure mode
    surfaced by the HIMS DEF 14A smoke test on 2026-05-15.
    """
    if not cell_text:
        return None
    m = _PCT_VALUE_RE.search(cell_text)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    if val <= 0.0:
        return None
    return val


# ── SEC Schedule 13D / 13D/A ownership parser (PRIMARY for >5%-holder CEOs) ──
#
# Architectural role: when a CEO is a 5%+ beneficial owner of their company,
# they (and only they) must file SC 13D within 10 days of crossing the
# threshold, and amend within 1 business day of material changes. The 13D
# is the AUTHORITATIVE source for beneficial ownership under SEC Rule
# 13d-3 — it states exactly:
#   Row 11. Aggregate Amount Beneficially Owned by Each Reporting Person
#   Row 13. Percent of Class Represented by Amount in Row (11)
#
# Below the 5% threshold (e.g. NVDA Huang at ~3.77%, ADBE Narayen at <1%),
# no 13D exists; DEF 14A is the fallback. For Canadian FPIs (SHOP) US
# disclosure rules don't apply; MIC is the fallback.
#
# The parser MUST verify "Names of Reporting Persons" matches the CEO's
# name — many issuers' 13Ds are filed by VC firms or founder trusts, NOT
# the current CEO. Returning a 13D figure for the wrong person would
# silently corrupt F5 scoring. The HIMS Dudum case (2026-05-15) is the
# only ticker among the first 9 audited where the SC 13D RP matched the
# CEO; for INTA/SHOP/LULU/ADBE/MRVL the 13Ds are by other parties.

# Cover-page anchors. The 13D cover is a numbered checklist; rows 1-14
# are well-defined.
_SC13D_NAMES_OF_RP = re.compile(
    r"(?:1\.|1\s+|Names\s+of\s+Reporting\s+Persons[\s:.]+)"
    r"\s*([A-Z][A-Za-z0-9\s.,'&\-]+?)"
    r"(?=\s*(?:2\.|2\s|Check\s+the\s+Appropriate\s+Box|S\.S\.|I\.R\.S\.|Source\s+of\s+Funds))",
    re.I,
)
_SC13D_AGGREGATE_AMOUNT = re.compile(
    r"(?:11\.|11\s+|Aggregate\s+Amount\s+Beneficially\s+Owned\s+by\s+Each\s+Reporting\s+Person)"
    r"[\s.]*([\d,]+)",
    re.I,
)
_SC13D_PERCENT_OF_CLASS = re.compile(
    r"(?:13\.|13\s+|Percent\s+of\s+Class\s+Represented\s+by\s+Amount\s+in\s+Row\s+\(11\))"
    r"[\s.]*(\d+(?:\.\d+)?)\s*%",
    re.I,
)


@dataclass
class SC13DOwnership:
    """Result of parsing a Schedule 13D / 13D/A cover page."""
    reporting_person: str | None = None
    aggregate_shares: int | None = None
    percent_of_class: float | None = None    # % per Row 13 (SEC Rule 13d-3 basis)
    matches_ceo: bool = False                # True iff reporting_person matches ceo_name_hint
    extraction_method: str = "none"
    state: str = "none"                      # 'disclosed_exact' | 'parser_uncertain' | 'rp_mismatch' | 'none'


def parse_sc13d_ownership(html: str, ceo_name_hint: str | None) -> SC13DOwnership:
    """Parse SC 13D / 13D/A cover-page beneficial ownership disclosure.

    Returns an SC13DOwnership with:
      - reporting_person: cover-page Item 1 value
      - aggregate_shares: Row 11 (full count, treating derivatives as if exercised per SEC Rule 13d-3)
      - percent_of_class: Row 13 (% of Class Represented)
      - matches_ceo: True iff reporting_person matches ceo_name_hint by last-name token

    `state` is one of:
      - 'disclosed_exact'   — all three fields extracted; RP matched CEO
      - 'rp_mismatch'       — fields extracted but RP is NOT the CEO; caller
                              should fall through to DEF 14A
      - 'parser_uncertain'  — fields partially extracted
      - 'none'              — couldn't find the cover page

    The strict-RP-match discipline prevents the silent-corruption failure
    mode where a venture firm's 13D would otherwise be persisted as the
    CEO's ownership (INTA Hill Investors case 2026-05-15).
    """
    if not html:
        return SC13DOwnership()

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    result = SC13DOwnership()

    # 1. Reporting Person
    m_rp = _SC13D_NAMES_OF_RP.search(text)
    if m_rp:
        rp = m_rp.group(1).strip().rstrip(".,")
        # Trim trailing labels that the lookahead missed
        for stop in ("Check the", "Member of", "(See", "SEC Use Only"):
            if stop in rp:
                rp = rp.split(stop)[0].rstrip()
        result.reporting_person = rp[:200]

    # 2. Aggregate Amount (Row 11)
    m_agg = _SC13D_AGGREGATE_AMOUNT.search(text)
    if m_agg:
        try:
            result.aggregate_shares = int(m_agg.group(1).replace(",", ""))
        except ValueError:
            pass

    # 3. Percent of Class (Row 13)
    m_pct = _SC13D_PERCENT_OF_CLASS.search(text)
    if m_pct:
        try:
            result.percent_of_class = float(m_pct.group(1))
        except ValueError:
            pass

    # 4. Match RP to CEO name (last-name token, case-insensitive)
    if ceo_name_hint and result.reporting_person:
        ceo_last = ceo_name_hint.split()[-1].lower().strip(".,")
        rp_lower = result.reporting_person.lower()
        # Match must be on word-boundary to avoid "Murphy" matching "Murphys Industries"
        if re.search(rf"\b{re.escape(ceo_last)}\b", rp_lower):
            result.matches_ceo = True

    # 5. State assignment
    if result.percent_of_class is not None and result.matches_ceo:
        result.state = "disclosed_exact"
        result.extraction_method = "sec_sc13d_cover"
    elif result.reporting_person and not result.matches_ceo:
        result.state = "rp_mismatch"  # caller should fall through
        result.extraction_method = "sec_sc13d_cover"
    elif result.percent_of_class is not None:
        # RP couldn't be matched but we got a percent — uncertain
        result.state = "parser_uncertain"
    else:
        result.state = "none"

    return result


# ── Canadian Management Information Circular (6-K) ownership parser ───────
#
# Canadian foreign-private issuers (and former-FPIs that recently converted
# to domestic SEC filers) file their AGM proxy circulars as 6-K/EX-99.1
# attachments, NOT as DEF 14A. The MIC ownership table has a different
# shape from a US DEF 14A:
#
#   - Section heading: "Principal Shareholders" (vs US "Security Ownership")
#   - Multi-class share structure is the norm (Class A subordinate +
#     Class B multiple/restricted voting + founder share)
#   - Per-class table: rows = share class, cols = shares owned, % of class,
#     % of total voting power. The CEO's TOTAL economic % is NOT directly
#     printed — it must be COMPUTED from the per-class breakdown.
#
# Canonical SHOP 2024 MIC structure (validated):
#   Class A Subordinate Voting Shares  646,932   (0.05% of class)
#   Class B Restricted Voting Shares   78,918,520 (99.57% of class)
#   Founder Share                      1         (100% of class)
#   Total outstanding: 1,209,155,635 Class A + 79,258,749 Class B + 1 founder
#   → Lütke economic equity = 79,565,453 / 1,288,414,385 = 6.18%
#
# Extraction strategy (deterministic, regex on plain text — same discipline
# as the rest of edgar_text_parser):
#   1. Strip HTML to text, normalise whitespace
#   2. Locate the "Principal Shareholders" / "Principal Holders" section
#   3. Within that section, extract the CEO's per-class shareholdings
#   4. Locate the outstanding-shares declaration anywhere in the doc
#   5. Compute total economic equity = sum(CEO shares) / sum(outstanding)
#   6. Also extract the voting-power aggregate (typically explicitly printed)
#
# Returns ProxyOwnership (same shape as DEF 14A path). multi_class_detected
# is True; extraction_method is "mic_html_text"; state is "disclosed_exact"
# when the computed equity > 0, "parser_uncertain" if outstanding totals
# missing, "not_disclosed" if the section itself isn't present.

# Outstanding-shares declaration: anchored by "issued and outstanding" so we
# capture the AGGREGATE total, not an in-section footnote breakdown that
# happens to use the same class label. Pattern allows a few intervening
# words ("Class A subordinate voting shares ... were issued and outstanding").
_MIC_OUTSTANDING_CLASS_A = re.compile(
    r"(\d{1,3}(?:,\d{3})+)\s+Class\s+A\s+subordinate\s+voting\s+shares"
    r"[^.]{0,200}?(?:issued\s+and\s+outstanding|outstanding)",
    re.I,
)
_MIC_OUTSTANDING_CLASS_B = re.compile(
    r"(\d{1,3}(?:,\d{3})+)\s+Class\s+B\s+(?:restricted|multiple)\s+voting\s+shares"
    r"[^.]{0,200}?(?:issued\s+and\s+outstanding|outstanding)",
    re.I,
)
_MIC_OUTSTANDING_FOUNDER = re.compile(
    r"(?:one|\d+)\s+founder\s+shares?\s+(?:were\s+|are\s+|was\s+)?(?:issued\s+and\s+outstanding|outstanding)",
    re.I,
)

# Per-class CEO shareholdings (within Principal Shareholders section).
# Footnote markers appear as either "(N)" or orphan "N)" depending on
# whether HTML stripped the opening paren. Both shapes accepted.
# Example: "Class A Subordinate Voting Shares 646,932 1) 0.05 % 0.03 %"
# Example: "Class B Restricted Voting Shares 78,918,520 (2) 99.57 % 39.05 %"
_MIC_CEO_CLASS_A_ROW = re.compile(
    r"Class\s+A\s+Subordinate\s+Voting\s+Shares\s+"
    r"(\d{1,3}(?:,\d{3})*)\s*(?:\(?\d+\)?\s+)?"
    r"(\d+(?:\.\d+)?)\s*%",
    re.I,
)
_MIC_CEO_CLASS_B_ROW = re.compile(
    r"Class\s+B\s+(?:Restricted|Multiple)\s+Voting\s+Shares\s+"
    r"(\d{1,3}(?:,\d{3})*)\s*(?:\(?\d+\)?\s+)?"
    r"(\d+(?:\.\d+)?)\s*%",
    re.I,
)
_MIC_CEO_FOUNDER_ROW = re.compile(
    r"Founder\s+Share\s+\(?\d*\)?\s*(\d+)\s+",
    re.I,
)

# Aggregate voting power for the CEO+affiliates block
_MIC_VOTING_POWER = re.compile(
    r"Aggregate\s+voting\s+power\s+attached\s+to\s+all\s+of\s+the\s+Company"
    r"['’]?s\s+outstanding\s+voting\s+shares\s+(\d+(?:\.\d+)?)\s*%",
    re.I,
)

# Section anchor — keep this loose; MICs vary slightly
_MIC_PRINCIPAL_HOLDERS_ANCHOR = re.compile(
    r"Principal\s+(?:Shareholders|Holders)",
    re.I,
)


def parse_mic_ownership(html: str, ceo_name_hint: str | None = None) -> ProxyOwnership:
    """
    Parse CEO economic equity % from a Canadian Management Information
    Circular (6-K/EX-99.1) — the structural counterpart to parse_proxy_ownership
    for filers without a DEF 14A.

    Computes total economic equity from per-class shareholdings, since the
    MIC does NOT print the aggregate economic % directly (only per-class
    percentages and aggregate VOTING power).

    Returns ProxyOwnership with multi_class_detected=True when successful.
    """
    if not html:
        return ProxyOwnership()

    # Strip HTML to plain text (BeautifulSoup if available, else minimal
    # tag stripper). Same approach as the rest of this module.
    text: str
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)

    result = ProxyOwnership(multi_class_detected=True)

    # Section anchor must be present — otherwise this isn't a MIC
    anchor = _MIC_PRINCIPAL_HOLDERS_ANCHOR.search(text)
    if not anchor:
        result.state = "not_disclosed"
        return result

    # Outstanding share counts (search the WHOLE doc — these may be quoted
    # before the section as well as inside it)
    m_a_out = _MIC_OUTSTANDING_CLASS_A.search(text)
    m_b_out = _MIC_OUTSTANDING_CLASS_B.search(text)
    m_f_out = _MIC_OUTSTANDING_FOUNDER.search(text)
    if not (m_a_out and m_b_out):
        result.state = "parser_uncertain"
        return result
    class_a_out = int(m_a_out.group(1).replace(",", ""))
    class_b_out = int(m_b_out.group(1).replace(",", ""))
    founder_out = 1 if m_f_out else 0
    total_out = class_a_out + class_b_out + founder_out
    if total_out <= 0:
        result.state = "parser_uncertain"
        return result

    # CEO per-class holdings — search ONLY within the Principal Shareholders
    # section (anchor + ~3000 chars window) to avoid grabbing a different
    # holder's table by accident
    section = text[anchor.start():anchor.start() + 3000]
    m_a_ceo = _MIC_CEO_CLASS_A_ROW.search(section)
    m_b_ceo = _MIC_CEO_CLASS_B_ROW.search(section)
    m_f_ceo = _MIC_CEO_FOUNDER_ROW.search(section)

    if not (m_a_ceo or m_b_ceo):
        # No CEO holdings in the section — could be a year where 5% threshold
        # wasn't met by anyone; record as parser_uncertain rather than 0
        result.state = "parser_uncertain"
        return result

    class_a_ceo = int(m_a_ceo.group(1).replace(",", "")) if m_a_ceo else 0
    class_b_ceo = int(m_b_ceo.group(1).replace(",", "")) if m_b_ceo else 0
    founder_ceo = int(m_f_ceo.group(1)) if m_f_ceo else 0

    ceo_total = class_a_ceo + class_b_ceo + founder_ceo
    if ceo_total <= 0:
        result.state = "parser_uncertain"
        return result

    result.ceo_equity_pct = (ceo_total / total_out) * 100.0
    result.extraction_method = "mic_html_text"
    result.state = "disclosed_exact"
    if ceo_name_hint:
        result.ceo_name = ceo_name_hint

    return result


# ── Founder detection (10-K or proxy text) ───────────────────────────────

_FOUNDER_PATTERNS: list[re.Pattern[str]] = [
    # "founder and CEO" / "co-founder and chief executive officer"
    re.compile(r"(?:co-?)?founder\s+and\s+(?:chief\s+executive|ceo)", re.I),
    # "CEO and (co-)founder" / "chief executive officer and co-founder"
    re.compile(
        r"(?:chief\s+executive(?:\s+officer)?|ceo)\s+and\s+(?:co-?)?founder",
        re.I,
    ),
    # "founded the company in 2010" / "founded XYZ in 2010"
    re.compile(r"founded\s+(?:the\s+company|[A-Z]\w+(?:\s+\w+)*)\s+in\s+\d{4}", re.I),
    # "co-founder ... serves/serving as CEO" within ~50 chars
    re.compile(
        r"(?:co-?)?founder.{0,50}?(?:serves?|serving)\s+as\s+"
        r"(?:(?:our\s+)?chief\s+executive|ceo)",
        re.I,
    ),
    # "CEO ... co-founder" within a short window (avoid cross-paragraph false positives)
    re.compile(r"(?:chief\s+executive(?:\s+officer)?|ceo).{0,50}?(?:co-?)?founder", re.I),
    # "is our [CEO|chief executive] and co-founder"
    re.compile(
        r"(?:is|serves\s+as)\s+(?:our\s+|the\s+)?(?:chief\s+executive(?:\s+officer)?|ceo)"
        r"\s+and\s+(?:co-?)?founder",
        re.I,
    ),
]


def parse_is_founder_ceo(text: str, ceo_name: str | None = None) -> bool | None:
    """
    Return True if text strongly indicates the CEO is also a company founder.
    Returns None (not False) when no signal is found — absence of evidence
    is not evidence of absence (many proxy statements don't mention founder status).

    `ceo_name`: when provided, founder-language matches must occur within
    ±200 chars of the CEO's name (full name OR last-name token) to count.
    Without this constraint the patterns false-positive on board-member
    bios in the proxy (e.g. AAPL's proxy mentions a director who is the
    "founder and CEO" of their own external venture). When `ceo_name`
    is None the legacy permissive behaviour is preserved for callers
    that haven't been updated.
    """
    if ceo_name:
        return _parse_founder_with_proximity(text, ceo_name)
    # Legacy fallback (permissive — known to false-positive)
    for pattern in _FOUNDER_PATTERNS:
        if pattern.search(text):
            return True
    return None


def _parse_founder_with_proximity(text: str, ceo_name: str) -> bool | None:
    """A founder pattern hit only counts when it's clearly the CEO's bio.

    The biographical convention in DEF 14A director-nominee tables is:
      `{Name} {Title-with-Founder-language} ... {Name} {CEO-Title} ...`
    Each director is listed sequentially with their own bio. A naive
    ±200 char proximity false-positives because the previous director's
    "Founder and CEO" can sit just before the current CEO's name.

    Tighter rule: the founder phrase must occur AFTER the CEO's name
    within +120 chars AND there must be no OTHER capitalized-name pattern
    (a typical "FirstName LastName" director-table delimiter) between
    them. We also require the matched substring to NOT be immediately
    preceded by ", " (which would put it in another director's compressed
    bio).

    Tests both full-name and last-name positions.
    """
    full = ceo_name.strip()
    last_name = full.split()[-1] if full else ""
    name_terms: list[str] = []
    if full:
        name_terms.append(full.lower())
    if last_name and last_name.lower() not in name_terms:
        name_terms.append(last_name.lower())
    if not name_terms:
        return None

    text_lower = text.lower()
    name_positions: list[int] = []
    for term in name_terms:
        if len(term) < 3:
            continue
        idx = 0
        while True:
            j = text_lower.find(term, idx)
            if j == -1:
                break
            name_positions.append(j + len(term))    # END of name occurrence
            idx = j + len(term)
    if not name_positions:
        return None

    # Compile a "next director" delimiter — capitalized FirstName LastName
    # (two consecutive capitalized words) — to detect the start of the
    # next director's bio.
    next_director = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")

    for pattern in _FOUNDER_PATTERNS:
        for m in pattern.finditer(text):
            for end_of_name in name_positions:
                # Founder phrase must come AFTER the CEO name within +120 chars
                gap = m.start() - end_of_name
                if not (0 <= gap <= 120):
                    continue
                # And no "next director" name should appear in the gap.
                between = text[end_of_name:m.start()]
                if next_director.search(between):
                    continue
                return True
    return None


# ── CEO tenure (proxy text) ───────────────────────────────────────────────

_TENURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:has\s+)?served\s+as\s+(?:(?:our\s+)?chief\s+executive|ceo)\s+(?:officer\s+)?since\s+(\d{4})", re.I),
    re.compile(r"appointed\s+(?:as\s+)?(?:(?:our\s+)?chief\s+executive|ceo)\s+(?:officer\s+)?in\s+(\d{4})", re.I),
    re.compile(r"(?:chief\s+executive|ceo)\s+(?:officer\s+)?since\s+(?:\w+\s+)?(\d{4})", re.I),
    re.compile(r"became\s+(?:(?:our\s+)?chief\s+executive|ceo)\s+(?:officer\s+)?in\s+(\d{4})", re.I),
]


def parse_ceo_tenure(text: str) -> float | None:
    """Return years as CEO calculated from 'since YYYY' or 'in YYYY' mentions."""
    for pattern in _TENURE_PATTERNS:
        m = pattern.search(text)
        if m:
            year = int(m.group(1))
            if 1980 <= year <= _CURRENT_YEAR:
                return float(_CURRENT_YEAR - year)
    return None


# ── Shared helper ─────────────────────────────────────────────────────────


def _find_relevant_paragraphs(
    text: str,
    keywords: list[str],
    max_chars: int = 8_000,
) -> list[str]:
    """Return paragraphs that contain any keyword, up to max_chars total chars."""
    sep = "\n\n" if "\n\n" in text else "\n"
    paragraphs = text.split(sep)
    kept: list[str] = []
    total = 0
    for para in paragraphs:
        para_lower = para.lower()
        if any(kw in para_lower for kw in keywords):
            kept.append(para.strip())
            total += len(para)
            if total >= max_chars:
                break
    return kept
