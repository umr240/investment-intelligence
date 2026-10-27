"""Check the stored external signals against their SEC sources (ADR-057 §2.6).

Each row's document is re-fetched from SEC (deterministic, no LLM) through the
extractors' own text pipeline, cut to what the model saw, and checked by
deepdive/signal_verifier.py. Before a row changes, its original value and band
are copied to model_value_numeric / model_confidence. A row whose stored URL is
not the filing's document (HIMS) gets the document URL from its accession, and
a NULL as_of_date gets the filing date. A quote none of whose fragments occur in
the re-fetched text is reported, not applied: the document text itself may differ.

Dry run by default; `--apply` writes, so back up first.

    uv run python scripts/verify_external_signals.py            # report
    uv run python scripts/verify_external_signals.py --apply    # write
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import date
from importlib.metadata import version
from typing import Any

from sqlalchemy import select

from config.settings import require_edgar_identity
from data.api._retry import sec_get_with_retry
from data.db import get_session
from data.edgar_companyfacts import _SUBMISSIONS_URL
from data.models.schema import Company, ExternalSignalRecord
from deepdive.external_signals import _EDGAR_DOC_URL, MODEL_TEXT_CHARS, html_to_text
from deepdive.signal_verifier import (
    QUOTE_NOT_IN_SOURCE,
    normalise,
    stored_band,
    verify_signal,
)

_MIN_FRAGMENT = 30  # a shorter fragment proves nothing about the document


def _get(url: str, identity: str) -> Any:
    time.sleep(0.12)  # SEC fair access: ~8 requests a second
    resp = sec_get_with_retry(url, headers={"User-Agent": identity}, label="verify_signals")
    if resp is None or resp.status_code != 200:
        raise RuntimeError(f"SEC fetch failed: {url}")
    return resp


def _filing(cik: int, accession: str, identity: str) -> tuple[str, date]:
    """The primary document URL and filing date of an accession, from submissions.json."""
    recent = _get(_SUBMISSIONS_URL.format(cik=cik), identity).json()["filings"]["recent"]
    i = recent["accessionNumber"].index(accession)
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{accession.replace('-', '')}/{recent['primaryDocument'][i]}"
    )
    return url, date.fromisoformat(recent["filingDate"][i])


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    identity = require_edgar_identity()
    texts: dict[str, str] = {}
    outcomes: Counter[str] = Counter()
    reported: list[str] = []
    print(f"beautifulsoup4 {version('beautifulsoup4')}; text cut to {MODEL_TEXT_CHARS} chars")
    with get_session() as session:
        rows = session.execute(
            select(ExternalSignalRecord, Company)
            .join(Company, Company.id == ExternalSignalRecord.company_id)
            .where(
                ExternalSignalRecord.extraction_method == "llm_anthropic",
                ExternalSignalRecord.verification.is_(None),
            )
            .order_by(ExternalSignalRecord.id)
        ).all()
        for row, co in rows:
            url, filed = str(row.source_url or ""), None
            if not _EDGAR_DOC_URL.match(url):
                url, filed = _filing(int(str(co.cik)), str(row.source_accession), identity)
            if url not in texts:
                texts[url] = html_to_text(_get(url, identity).text)[:MODEL_TEXT_CHARS]
            text = texts[url]
            value = row.signal_value_numeric
            quote = str(row.source_quote or "")
            v = verify_signal(value, quote, str(row.signal_unit or ""), text)
            src = normalise(text)
            fragments = [
                f for f in normalise(quote).split("...") if len(f.strip()) >= _MIN_FRAGMENT
            ]
            if v.outcome == QUOTE_NOT_IN_SOURCE and not any(f.strip() in src for f in fragments):
                reported.append(
                    f"{co.ticker} {row.signal_name}: no quote fragment in the re-fetched text"
                )
                continue
            band = stored_band(str(row.extraction_confidence), v.ceiling)
            kept = value if v.kept and band != "not_disclosed" else None
            outcomes[v.outcome] += 1
            changes = [f"{row.extraction_confidence}->{band}"]
            if kept != value:
                changes.append(f"value {value}->None")
            if url != row.source_url:
                changes.append(f"url -> {url}")
            if row.as_of_date is None and filed is not None:
                changes.append(f"as_of_date -> {filed}")
            flags = "".join(f" +{f}" for f in v.flags)
            label = f"#{row.id} {co.ticker} {row.signal_name}"
            print(f"  {label}: {v.outcome}{flags}; {', '.join(changes)}")
            if apply:
                rec: Any = row  # Column-style model: mypy types its attributes as Column[...]
                rec.model_value_numeric, rec.model_confidence = value, rec.extraction_confidence
                rec.signal_value_numeric, rec.extraction_confidence = kept, band
                record = json.loads(v.to_json())
                if url != rec.source_url:  # §2.6: nothing is overwritten that is not first copied
                    record["previous_source_url"] = rec.source_url
                rec.verification = json.dumps(record, sort_keys=True)
                rec.source_url = url
                if rec.as_of_date is None and filed is not None:
                    rec.as_of_date = filed
        print(f"{len(rows)} rows: " + ", ".join(f"{k} {n}" for k, n in sorted(outcomes.items())))
        for line in reported:
            print(f"  reported, not applied: {line}")
        if apply:
            print(f"applied to {sum(outcomes.values())} rows")
        else:
            session.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
