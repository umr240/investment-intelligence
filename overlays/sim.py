"""
SIM — Structural Intelligence Moat overlay (DEC-33 / Phase 5N).

A soft-gate overlay scored only for technology-sector tickers, separate from
F1-F7 and NOT contributing to composite_score. Tags the company's AI-native
architecture along five binary axes (Hirshleifer's "intelligence compounding"
extended to ontology-driven systems).

EPISTEMIC TIER: ◯ (architectural hypothesis, not academic validation)

There is no ★★★ peer-reviewed paper that validates "ontology-driven companies
outperform". AI-native architecture is ~3 years old as a commercial reality;
the academic lag for ★★★ validation is 10-20 years. SIM is therefore tagged
◯ — same convention as F6's NRR/GRR practitioner heuristics — and explicitly
documented as a heuristic-tier signal. Once the literature catches up (the
extensions of Peters-Taylor on intangible capital, Hirshleifer-Hsu-Li on
innovative efficiency, and Patatoukas on concentration are the closest
anchors today), the tier can be upgraded.

HONEST LIMIT (recorded 2026-05-11, do not waste a session re-solving this):

SIM-3's regex-over-10-K approach catches what companies SAY about their
architecture, not what they ARE. Two failure modes:
  • PLTR fires because Palantir literally writes "Ontology" 30+ times in
    its 10-K — they've branded the architecture and tell the SEC about it.
  • Tempus AI may genuinely be ontology-native but disclose it in
    different language ("multimodal clinical-molecular data integration",
    "structured oncology knowledge representation"). The regex misses them.

Workarounds attempted and rejected:
  • Curated allowlist — memorialises prior knowledge; defeats discovery.
    If you already know TEM is AI-native, the system telling you so is
    valueless. The whole point of universe-scale screening is surfacing
    names you DON'T already know.
  • Keyword-density gate — same regex problem at a different threshold;
    still depends on the company's choice of disclosure vocabulary.
  • Web search — trades determinism for narrative cycle noise; breaks the
    "same dive run twice → same result" audit guarantee the codebase
    rests on.
  • LLM judgment over 10-K text — introduces drift across model
    versions; technically possible (would live behind an opt-in
    --llm-sim-review flag) but not a default path.

There is NO clean automated answer to "is this company architecturally
AI-native" at universe scale right now. SIM v1 catches the subset that
self-discloses ontology architecture in their 10-K. Companies that ARE
ontology-native but use different vocabulary (or are pre-IPO, or are
foreign filers) WILL be missed. Accept the limit; don't re-solve it
with the same dead-end approaches.

The 5 binary tests:

  SIM-1  Structural Embeddedness — remove the AI layer entirely; does the
         core workflow still function? Subjective; emits manual_review.
  SIM-2  Proprietary Knowledge Accumulation — does the company accumulate
         domain data external foundation models can't replicate from public
         sources? Subjective; emits manual_review.
  SIM-3  Reasoning vs Pattern-Matching — formal ontology / knowledge graph
         architecture present? Auto-detectable via 10-K keyword regex.
  SIM-4  Intelligence Compounding Rate — does each client / transaction
         make the system smarter for all users (cross-client learning)?
         Subjective; emits manual_review.
  SIM-5  Domain Specificity Depth — narrower is better. Detectable
         (partially) via business-description specificity + industry tag.

Pass: 4/5 or 5/5 (with at least 2 auto-detected tests passing).
Indeterminate: 3/5 (likely AI-adjacent, not AI-native).
Fail: ≤ 2/5.

The verdict NEVER excludes a ticker from F1-F7 scoring. It surfaces as a
separate dive panel. Read alongside F1-F7, weigh judgment, decide.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Sector gate ──────────────────────────────────────────────────────────


_TECH_SECTOR_TOKENS = frozenset({
    "technology",
})
_TECH_INDUSTRY_TOKENS = (
    "software",
    "information technology",
    "semiconductors",
    "internet",
    "computer hardware",
    "electronic components",
    "tech",
)


def is_ai_relevant_sector(sector: str | None, industry: str | None) -> bool:
    """Tech-sector gate for SIM eligibility (DEC-33 scope decision).

    Returns True when sector is "Technology" OR industry name starts with
    one of the AI-adjacent tech industry tokens. Conservative — Healthcare
    + biotech may host AI-native plays but the keyword space differs
    enough that they need a separate detector. SIM v1 stays tech-only.
    """
    if sector and sector.lower() in _TECH_SECTOR_TOKENS:
        return True
    if industry:
        low = industry.lower()
        return any(tok in low for tok in _TECH_INDUSTRY_TOKENS)
    return False


# ── SIM-3 ontology / knowledge-graph detector ────────────────────────────


# Phrases that suggest formal ontology, knowledge graph, or typed-entity
# reasoning architecture. Distinct from generic AI/ML mentions —
# "we use GPT-4 with RAG" doesn't fire SIM-3, but "typed entity ontology"
# or "knowledge graph of customer relationships" does.
_SIM3_ONTOLOGY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:typed\s+)?ontology\b", re.I),
    re.compile(r"\bknowledge[\s\-]?graph(?:s)?\b", re.I),
    re.compile(r"\b(?:semantic|formal)\s+(?:layer|model|representation)\b", re.I),
    re.compile(r"\b(?:RDF|OWL|SPARQL|graph[\s\-]?database)\b", re.I),
    # MCP (Model Context Protocol) servers — Anthropic's explicit ontology
    # layer protocol. Companies that ship MCP servers are building ontology
    # interfaces over their domain.
    re.compile(r"\bmodel\s+context\s+protocol\b", re.I),
    re.compile(r"\bMCP\s+server", re.I),
    # Domain object models with formal typing
    re.compile(r"\b(?:domain|entity|object)\s+(?:ontology|model|graph)\b", re.I),
    # Palantir-style operational ontology language
    re.compile(r"\boperational\s+ontology\b", re.I),
]

# Negative pattern set — phrases that suggest pattern-matching / generic
# LLM use rather than ontology architecture. When these dominate over the
# positives, SIM-3 fails.
_SIM3_NEGATIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b(?:GPT|Claude|Gemini|Llama)[\s\-]?(?:\d|powered|based)?"
        r"\s+(?:with\s+)?RAG\b",
        re.I,
    ),
    re.compile(r"\bretrieval[\s\-]?augmented\s+generation\b", re.I),
    re.compile(r"\bprompt\s+(?:engineering|chain)\b", re.I),
]


# ── SIM-5 domain narrowness detector ─────────────────────────────────────


# Industry strings suggesting deep, narrow vertical (positive signal).
# "AI for healthcare imaging" beats "AI for enterprise"; codify via
# industry-text specificity.
_SIM5_NARROW_TOKENS = (
    "vertical", "vertically integrated", "specialty", "specific",
    "domain[-\\s]+specific", "industry[-\\s]+specific",
)
_SIM5_BROAD_NEGATIVES = (
    "any industry", "general[-\\s]+purpose", "horizontal", "broad market",
    "across industries", "multi[-\\s]+industry", "enterprise (?:platform|software)",
)


# ── Core compute ─────────────────────────────────────────────────────────


def _compute_sim3(text: str) -> tuple[bool, dict[str, Any]]:
    """Detect ontology / knowledge-graph architecture in 10-K text.

    Counts ALL matches of each pattern (via findall) — a single 10-K may
    mention "Ontology" 30+ times for a true ontology-native company.
    Earlier version used `search()` returning only first hit; calibration
    test on PLTR (canonical ontology case) under-counted with just 1 hit.
    """
    positive_count = 0
    positive_samples: list[str] = []
    for pattern in _SIM3_ONTOLOGY_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            positive_count += len(matches)
            if len(positive_samples) < 6:
                sample = matches[0]
                positive_samples.append(sample if isinstance(sample, str) else str(sample))

    negative_count = 0
    negative_samples: list[str] = []
    for pattern in _SIM3_NEGATIVE_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            negative_count += len(matches)
            if len(negative_samples) < 6:
                sample = matches[0]
                negative_samples.append(sample if isinstance(sample, str) else str(sample))

    # Pass when at least 5 total positive mentions across the ontology
    # pattern set AND positives dominate negatives. The 5-count threshold
    # filters out incidental mentions (one ontology reference in a risk
    # factors section ≠ ontology-native architecture); a true
    # ontology-native company describes it repeatedly across Item 1 + 7.
    pass_ = positive_count >= 5 and positive_count > negative_count
    return pass_, {
        "positive_hit_count": positive_count,
        "negative_hit_count": negative_count,
        "positive_hits": positive_samples,
        "negative_hits": negative_samples,
        "method": "regex over 10-K Item 1 + 7 (findall counts all matches)",
    }


def _compute_sim5(industry: str | None, business_description: str) -> tuple[bool, dict[str, Any]]:
    """Detect domain narrowness — narrower industry / more vertical phrasing → pass.

    Conservative — false negatives preferred over false positives here.
    """
    narrow_hits: list[str] = []
    broad_hits: list[str] = []

    for tok in _SIM5_NARROW_TOKENS:
        if re.search(rf"\b{tok}\b", business_description, re.I):
            narrow_hits.append(tok)
    for tok in _SIM5_BROAD_NEGATIVES:
        if re.search(rf"\b{tok}\b", business_description, re.I):
            broad_hits.append(tok)

    # Heuristic: industries with specific vertical names tend to be
    # narrower. "Software - Application" is broad; "Software - Healthcare
    # Information" is narrow. Detect via dash-separated qualifier.
    industry_narrow = bool(industry and "-" in industry and len(industry) > 25)
    pass_ = (
        (len(narrow_hits) >= 1 or industry_narrow)
        and len(narrow_hits) >= len(broad_hits)
    )
    return pass_, {
        "narrow_hits": narrow_hits,
        "broad_hits": broad_hits,
        "industry_narrow_signal": industry_narrow,
        "industry": industry,
    }


async def run_sim(
    ticker: str,
    *,
    sector: str | None,
    industry: str | None,
    tenk_text: str = "",
    business_description: str = "",
) -> dict[str, Any]:
    """Compute SIM 5-test scorecard.

    Returns a dict that mirrors other overlay outputs (ICA, PSA, BEW)
    for uniform orchestrator + CLI handling. NOT auto-summed into
    composite_score per DEC-33 scope decision.

    `tenk_text` is the concatenated Item 1 + Item 7 text from the latest
    10-K; the caller fetches via the same TenK section reader as customer
    concentration / retention. Empty string is acceptable — SIM-3 will
    simply not auto-detect and SIM-5 will rely on industry signal alone.
    """
    if not is_ai_relevant_sector(sector, industry):
        return {
            "ok": False,
            "reason": (
                f"sector='{sector}' / industry='{industry}' is not AI-relevant "
                f"(DEC-33 SIM scope: technology sector only)"
            ),
            "verdict": "not_applicable",
        }

    # SIM-1 / SIM-2 / SIM-4 — emit manual_review placeholders.
    # These are judgment calls that text regex cannot reliably perform.
    sim1 = {
        "pass": None,
        "manual_review": True,
        "prompt": (
            "Remove the AI layer entirely from the company's stack. Does "
            "the core workflow still function? If YES → AI is peripheral, "
            "SIM-1 fails. If NO → AI is structural, SIM-1 passes."
        ),
    }
    sim2 = {
        "pass": None,
        "manual_review": True,
        "prompt": (
            "Is the company accumulating domain data that external "
            "foundation models cannot replicate from public sources? "
            "Signals: regulated / private operational data (legal "
            "conflicts, clinical notes, deal flow, physical sensor "
            "streams). Hard negative: training data is publicly available."
        ),
    }
    sim4 = {
        "pass": None,
        "manual_review": True,
        "prompt": (
            "Does each additional client / transaction make the system "
            "meaningfully smarter for ALL users (network-effect on the "
            "underlying intelligence)? Signal: model retrains on "
            "anonymised cross-client data, industry benchmark improves "
            "over time, NRR accelerates with AI feature adoption. Hard "
            "negative: each client's AI is siloed."
        ),
    }

    sim3_pass, sim3_signals = _compute_sim3(tenk_text)
    sim5_pass, sim5_signals = _compute_sim5(industry, business_description or tenk_text)

    # Auto-detected pass count (excludes manual_review tests).
    auto_pass = int(sim3_pass) + int(sim5_pass)
    auto_total = 2    # only SIM-3 + SIM-5 are auto-detected

    # Verdict on AUTO-DETECTED tests only. Final verdict requires manual review
    # of SIM-1/2/4 to upgrade — surface as "auto-detected" so user knows.
    if auto_pass == 2:
        verdict = "auto_passes_ontology_and_narrowness"
    elif auto_pass == 1:
        verdict = "auto_partial_one_test_only"
    else:
        verdict = "auto_fails_no_ontology_signal"

    return {
        "ok": True,
        "ticker": ticker,
        "epistemic_tier": "heuristic_circle",
        "sector_check_passed": True,
        "tests": {
            "SIM-1_structural_embeddedness": sim1,
            "SIM-2_proprietary_knowledge": sim2,
            "SIM-3_reasoning_vs_pattern_match": {
                "pass": sim3_pass,
                "manual_review": False,
                **sim3_signals,
            },
            "SIM-4_intelligence_compounding": sim4,
            "SIM-5_domain_specificity": {
                "pass": sim5_pass,
                "manual_review": False,
                **sim5_signals,
            },
        },
        "auto_pass_count": auto_pass,
        "auto_total": auto_total,
        "verdict": verdict,
        "interpretation": (
            "AUTO-DETECTED layer: SIM-3 (ontology / knowledge-graph "
            "architecture in 10-K) and SIM-5 (domain narrowness) are "
            "regex-detectable. SIM-1/2/4 are judgment calls — surface as "
            "manual_review placeholders. Final verdict requires the human "
            "to score the manual_review entries. Per DEC-33 this is NOT "
            "added to composite_score and never excludes a ticker from "
            "F1-F7."
        ),
        "academic_anchors": [
            "Peters-Taylor (2017) JFE — intangible capital ★★★ "
            "(adjacent: SIM extends to ontology-as-asset)",
            "Hirshleifer-Hsu-Li (2013) JFE — innovative efficiency ★★★ "
            "(adjacent: SIM-4 maps to intelligence compounding)",
            "Patatoukas (2012) — concentration effects ★★★ "
            "(adjacent: SIM-5 narrow-domain analogy)",
            "NOTE: SIM itself is ◯ (architectural hypothesis), NOT ★★★ "
            "validated. Tagged honestly.",
        ],
    }
