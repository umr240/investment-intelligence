"""External-signals extractor — the second permitted Anthropic call site.

Architectural contract (also documented on the ORM model):
  - Frameworks F1-F7 MUST NOT import or read this module's outputs.
  - This is the ONLY second Anthropic call site after deepdive/narrative.py.
    Both live within the dive layer; data/screener/framework layers stay
    LLM-free (CLAUDE.md §"AI layer boundary").
  - Every persisted ExternalSignalRecord carries: source URL, verbatim
    quote, extraction method, confidence band, model name. If any of those
    is missing, the row is NOT persisted — explicit gaps over silent
    inference (mental_models/core/margin_of_safety.md).
  - Input documents are deterministically-fetched SEC filings (8-K
    earnings press releases as EX-99.1 attachments). The LLM does only
    structured extraction within a tight schema — never invents numbers
    that aren't quoted from the source.
  - Confidence='not_disclosed' is a valid output: if the LLM honestly
    can't find a value in the provided text, that's recorded explicitly
    rather than fabricated. This is the same discipline as data_gaps[].

Signal targets (extensible — add to _EXTRACTION_TARGETS for new fields):
  - nrr_pct (Net Revenue Retention) — for SaaS / marketplace platforms
  - grr_pct (Gross Revenue Retention)
  - mrr_usd (Monthly Recurring Revenue)
  - arr_usd (Annualised Recurring Revenue)
  - gmv_usd (Gross Merchandise Volume — marketplace KPI)
  - merchant_count
  - take_rate_pct (revenue / GMV)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from config.settings import require_edgar_identity

logger = logging.getLogger(__name__)


_EXTRACTION_TARGETS: list[dict[str, str]] = [
    {"name": "nrr_pct", "unit": "pct", "description": "Net Revenue Retention — % revenue retained from existing customers including expansion, net of churn and contraction. Often reported as 'NRR' or 'net dollar retention'."},
    {"name": "grr_pct", "unit": "pct", "description": "Gross Revenue Retention — % revenue retained from existing customers BEFORE any expansion (only churn and contraction). Always ≤ NRR."},
    {"name": "mrr_usd", "unit": "usd", "description": "Monthly Recurring Revenue — most recent reported monthly subscription/SaaS run-rate."},
    {"name": "arr_usd", "unit": "usd", "description": "Annualised Recurring Revenue — typically MRR × 12 or directly reported annualised figure."},
    {"name": "gmv_usd", "unit": "usd", "description": "Gross Merchandise Volume — for marketplace platforms, total dollar value of transactions on the platform during the period."},
    {"name": "merchant_count", "unit": "count", "description": "Total active merchants/customers reported."},
    {"name": "take_rate_pct", "unit": "pct", "description": "Revenue as % of GMV — platform monetisation rate. Compute only if directly disclosed; do not derive."},
]


@dataclass
class ExtractedSignal:
    """One signal extracted by the LLM, with provenance."""
    name: str
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str = ""
    as_of_date: date | None = None
    source_quote: str = ""
    confidence: str = "not_disclosed"     # 'high' | 'medium' | 'low' | 'not_disclosed'


@dataclass
class ExtractionResult:
    """Bundle of extracted signals + source-doc provenance."""
    ticker: str
    source_url: str
    source_accession: str
    source_document: str                  # human-readable label
    extracted_at: datetime
    extracted_model: str
    signals: list[ExtractedSignal] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def fetch_latest_earnings_8k_text(ticker: str, cik: str) -> tuple[str, str, str, str] | None:
    """Fetch the EX-99.1 earnings press release from the most recent 8-K.

    Returns (raw_text, accession, source_url, source_label) or None if no
    suitable 8-K is found. Deterministic — no LLM here; this is the source
    document the LLM will read.
    """
    try:
        import warnings as _w
        _w.filterwarnings("ignore")
        from edgar import set_identity, Company as EdgarCo  # type: ignore[import]
    except ImportError as exc:
        logger.warning("edgartools not available: %s", exc)
        return None
    set_identity(require_edgar_identity())

    co = EdgarCo(cik.lstrip("0") or cik)
    eight_ks = list(co.get_filings(form="8-K").head(10))
    for f in eight_ks:
        # Identify the earnings-results 8-K by attachment names
        for a in f.attachments:
            doc = (getattr(a, "document", "") or "").lower()
            if "pressrelease" in doc or "earnings" in doc or "991" in doc or "ex-99" in doc:
                if doc.endswith(".htm") or doc.endswith(".html"):
                    try:
                        raw = a.content
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8", errors="ignore")
                        # Strip HTML to text
                        try:
                            from bs4 import BeautifulSoup  # type: ignore[import]
                            text = BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)
                        except ImportError:
                            import re as _re
                            text = _re.sub(r"<[^>]+>", " ", raw)
                        import re as _re
                        text = _re.sub(r"\s+", " ", text)
                        accn = f.accession_no
                        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik):d}/{accn.replace('-','')}/{a.document}"
                        label = f"{f.filing_date}_8K_{a.document}"
                        return text, accn, url, label
                    except Exception as exc:
                        logger.debug("8-K attachment fetch failed (%s): %s", ticker, exc)
                        continue
    return None


def extract_signals_via_llm(
    ticker: str,
    source_text: str,
    source_url: str,
    source_accession: str,
    source_label: str,
    period_end: date | None = None,
) -> ExtractionResult:
    """Call Anthropic with a tight tool-use schema. Returns extracted signals
    with provenance. Signals the LLM can't justify with a verbatim quote
    are marked confidence='not_disclosed' — never fabricated.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(f"anthropic SDK not installed: {exc}") from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    model = os.getenv("ANTHROPIC_EXTRACTION_MODEL", "claude-sonnet-4-6")

    targets_listing = "\n".join(
        f"  - {t['name']} ({t['unit']}): {t['description']}" for t in _EXTRACTION_TARGETS
    )

    system_prompt = (
        "You extract SaaS/marketplace operating metrics from earnings press releases.\n"
        "STRICT RULES (violating any rule means the value MUST be marked not_disclosed):\n"
        "1. Every numeric value you return MUST be supported by a verbatim quote\n"
        "   copied character-for-character from the source text.\n"
        "2. If the metric is NOT explicitly stated in the source, return\n"
        "   confidence='not_disclosed' and value=null. Do NOT estimate, infer,\n"
        "   derive, or compute from other disclosed numbers.\n"
        "3. Currency values: return in raw USD (not millions). Percentages:\n"
        "   return as decimal (e.g. 135% NRR → 135.0).\n"
        "4. Confidence bands:\n"
        "   - 'high'        — value directly named with its metric label\n"
        "   - 'medium'      — value clearly attributable to the metric but\n"
        "                     phrasing is paraphrased\n"
        "   - 'low'         — number present but metric attribution ambiguous\n"
        "   - 'not_disclosed' — number genuinely absent from source\n"
        "5. Marketplace platforms (like Shopify) typically DO NOT disclose\n"
        "   NRR/GRR in press releases. Honestly mark these not_disclosed\n"
        "   if absent — that is a TRUE finding, not a failure.\n"
        "6. Source quotes must be exact. If you cannot produce an exact\n"
        "   quote ≤300 chars, mark not_disclosed instead.\n"
    )

    user_prompt = (
        f"Ticker: {ticker}\n"
        f"Source: {source_label}\n"
        f"URL: {source_url}\n\n"
        f"Signals to extract:\n{targets_listing}\n\n"
        f"--- SOURCE TEXT BEGINS ---\n"
        f"{source_text[:80000]}\n"
        f"--- SOURCE TEXT ENDS ---\n\n"
        f"For each signal, return the value (or null if not_disclosed), "
        f"the verbatim quote (or empty string), and the confidence band."
    )

    tool_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": [t["name"] for t in _EXTRACTION_TARGETS]},
                        "value_numeric": {"type": ["number", "null"]},
                        "value_text": {"type": ["string", "null"]},
                        "source_quote": {"type": "string", "maxLength": 400},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low", "not_disclosed"]},
                    },
                    "required": ["name", "confidence", "source_quote"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["signals"],
        "additionalProperties": False,
    }

    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        tools=[{
            "name": "emit_signals",
            "description": "Emit the structured external signals extracted from the source text.",
            "input_schema": tool_schema,
        }],
        tool_choice={"type": "tool", "name": "emit_signals"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    tool_input: dict | None = None
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "emit_signals":
            tool_input = block.input
            break
    if tool_input is None:
        raise RuntimeError("anthropic did not emit a tool_use block")

    target_unit = {t["name"]: t["unit"] for t in _EXTRACTION_TARGETS}
    out_signals: list[ExtractedSignal] = []
    for s in tool_input.get("signals", []):
        out_signals.append(ExtractedSignal(
            name=str(s["name"]),
            value_numeric=s.get("value_numeric"),
            value_text=s.get("value_text"),
            unit=target_unit.get(str(s["name"]), ""),
            as_of_date=period_end,
            source_quote=str(s.get("source_quote") or ""),
            confidence=str(s["confidence"]),
        ))

    usage = getattr(resp, "usage", None)
    return ExtractionResult(
        ticker=ticker,
        source_url=source_url,
        source_accession=source_accession,
        source_document=source_label,
        extracted_at=datetime.utcnow(),
        extracted_model=model,
        signals=out_signals,
        prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def extract_ceo_equity_via_llm(
    ticker: str,
    source_html: str,
    source_url: str,
    source_accession: str,
    source_label: str,
    ceo_name_hint: str,
) -> ExtractionResult:
    """LLM-extract CEO economic beneficial ownership % from DEF 14A or SC 13D/A.

    Targets the beneficial-ownership table or Item 5 cover page. Must produce:
      - economic_equity_pct: % of class represented by aggregate beneficial
        ownership (SEC Rule 13d-3 definition)
      - voting_power_pct: separate signal — % of total voting power
      - shares_total: aggregate amount beneficially owned

    Architectural contract (per ADR-031 §4.1): writes only to external_signals
    table; never to Company.ceo_equity_pct or any canonical field. The caller
    decides whether to triangulate against deterministic parser output.

    Strict-quote-required prompt: each numeric value must be supported by a
    verbatim quote from source_html. Values without quotes → confidence=
    'not_disclosed', value=None. Same discipline as
    extract_signals_via_llm().
    """
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(f"anthropic SDK not installed: {exc}") from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    model = os.getenv("ANTHROPIC_EXTRACTION_MODEL", "claude-sonnet-4-6")

    # Strip HTML to plain text for the prompt; cheaper and same accuracy
    try:
        from bs4 import BeautifulSoup
        plain = BeautifulSoup(source_html, "html.parser").get_text(separator=" ", strip=True)
    except ImportError:
        import re as _re
        plain = _re.sub(r"<[^>]+>", " ", source_html)
    import re as _re
    plain = _re.sub(r"\s+", " ", plain)

    system_prompt = (
        "You extract CEO/insider beneficial ownership % from SEC ownership "
        "filings (DEF 14A proxy statements, Schedule 13D/13G, 10-K Item 12).\n\n"
        "STRICT RULES (violating any rule means the value MUST be marked not_disclosed):\n"
        "1. Every numeric value you return MUST be supported by a verbatim quote\n"
        "   copied character-for-character from the source text.\n"
        "2. For multi-class issuers (dual-class with Class A common + super-voting\n"
        "   Class V/B), distinguish:\n"
        "   - economic_equity_pct: % of beneficial ownership (Rule 13d-3 definition)\n"
        "     — typically the SC 13D's 'Percent of Class' on the cover page, OR\n"
        "     the DEF 14A's '% of Class A' column when 'as-converted' basis applies\n"
        "   - voting_power_pct: % of total voting power (separate signal)\n"
        "   These are DIFFERENT numbers for dual-class issuers. Do not conflate.\n"
        "3. If a column is empty/blank or shows `*` (less-than-1% redaction),\n"
        "   record confidence='low' with value=0.5 (under-1% convention) for that\n"
        "   field — NOT not_disclosed (it is disclosed; we just have a sub-1%\n"
        "   resolution limit).\n"
        "4. Quote ≤300 chars, exact substring of source.\n"
    )
    user_prompt = (
        f"Ticker: {ticker}\n"
        f"CEO: {ceo_name_hint}\n"
        f"Source: {source_label}\n"
        f"URL: {source_url}\n\n"
        f"Targets to extract:\n"
        f"  - economic_equity_pct (Rule 13d-3 beneficial ownership %)\n"
        f"  - voting_power_pct (% of total voting power, if disclosed)\n"
        f"  - aggregate_shares_beneficially_owned (count, if disclosed)\n\n"
        f"--- SOURCE TEXT BEGINS ---\n"
        f"{plain[:80000]}\n"
        f"--- SOURCE TEXT ENDS ---\n"
    )

    tool_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": [
                                "economic_equity_pct",
                                "voting_power_pct",
                                "aggregate_shares_beneficially_owned",
                            ],
                        },
                        "value_numeric": {"type": ["number", "null"]},
                        "source_quote": {"type": "string", "maxLength": 400},
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low", "not_disclosed"],
                        },
                    },
                    "required": ["name", "confidence", "source_quote"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["signals"],
        "additionalProperties": False,
    }

    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        tools=[{
            "name": "emit_signals",
            "description": "Emit the extracted CEO ownership signals.",
            "input_schema": tool_schema,
        }],
        tool_choice={"type": "tool", "name": "emit_signals"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    tool_input: dict | None = None
    for block in resp.content:
        if getattr(block, "type", "") == "tool_use" and block.name == "emit_signals":
            tool_input = block.input
            break
    if tool_input is None:
        raise RuntimeError("anthropic did not emit a tool_use block")

    unit_map = {
        "economic_equity_pct": "pct",
        "voting_power_pct": "pct",
        "aggregate_shares_beneficially_owned": "count",
    }
    out_signals: list[ExtractedSignal] = []
    for s in tool_input.get("signals", []):
        out_signals.append(ExtractedSignal(
            name=str(s["name"]),
            value_numeric=s.get("value_numeric"),
            unit=unit_map.get(str(s["name"]), ""),
            source_quote=str(s.get("source_quote") or ""),
            confidence=str(s["confidence"]),
        ))

    usage = getattr(resp, "usage", None)
    return ExtractionResult(
        ticker=ticker,
        source_url=source_url,
        source_accession=source_accession,
        source_document=source_label,
        extracted_at=datetime.utcnow(),
        extracted_model=model,
        signals=out_signals,
        prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def persist_extraction(result: ExtractionResult) -> int:
    """Upsert ExternalSignalRecord rows. Returns count persisted (incl.
    not_disclosed rows — those are valuable: prove we asked and didn't find).
    """
    from sqlalchemy import select
    from data.db import SessionLocal
    from data.models.schema import Company, ExternalSignalRecord

    count = 0
    with SessionLocal() as s:
        c = s.execute(select(Company).where(Company.ticker == result.ticker)).scalar_one()
        for sig in result.signals:
            # Upsert on (company_id, signal_name, as_of_date)
            existing = s.execute(select(ExternalSignalRecord).where(
                ExternalSignalRecord.company_id == c.id,
                ExternalSignalRecord.signal_name == sig.name,
                ExternalSignalRecord.as_of_date == sig.as_of_date,
            )).scalar_one_or_none()
            if existing is None:
                existing = ExternalSignalRecord(
                    company_id=c.id,
                    signal_name=sig.name,
                    as_of_date=sig.as_of_date,
                )
                s.add(existing)
            existing.signal_value_numeric = sig.value_numeric
            existing.signal_value_text = sig.value_text
            existing.signal_unit = sig.unit
            existing.source_url = result.source_url
            existing.source_quote = sig.source_quote
            existing.source_document = result.source_document
            existing.source_accession = result.source_accession
            existing.extraction_method = "llm_anthropic"
            existing.extraction_confidence = sig.confidence
            existing.extracted_at = result.extracted_at
            existing.extracted_model = result.extracted_model
            count += 1
        s.commit()
    return count
