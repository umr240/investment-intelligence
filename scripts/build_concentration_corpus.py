"""Build ADR-018 §6.2's customer-concentration validation corpus.

The §6.2 implementation gate was satisfied manually and recorded only in a
comment in edgar_text_parser.py ("validated against AAPL/NVDA/AMSC/FAST/MSFT/
INTA/TSLA — 7/7"). This snapshots those filings so the claim becomes a test.

One-off: uv run python scripts/build_concentration_corpus.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings  # noqa: E402
from data.edgar_fetcher import _read_tenk_sections  # noqa: E402

# The exact cohort named in the parser comment and ADR-018 §6.2.
TICKERS = ["AAPL", "NVDA", "AMSC", "FAST", "MSFT", "INTA", "TSLA"]

OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "filings"


def main() -> int:
    import warnings

    warnings.filterwarnings("ignore")
    from edgar import Company, set_identity

    if not settings.edgar_identity:
        print("EDGAR_IDENTITY unset — refusing to hit SEC without a fair-use header")
        return 1
    set_identity(settings.edgar_identity)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []

    for ticker in TICKERS:
        try:
            co = Company(ticker)
            filings = co.get_filings(form="10-K")
            if not filings:
                print(f"  {ticker:5} NO 10-K FOUND")
                continue
            filing = filings.latest()
            if filing is None or isinstance(filing, list):
                print(f"  {ticker:5} no single latest 10-K")
                continue
            tenk = filing.obj()
            sections = _read_tenk_sections(tenk)
            if not sections:
                print(f"  {ticker:5} no sections readable")
                continue

            text = "\n\n".join(sections.values())
            path = OUT_DIR / f"{ticker}_10k_sections.txt.gz"
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                fh.write(text)

            manifest.append(
                {
                    "ticker": ticker,
                    "cik": str(co.cik),
                    "accession": filing.accession_no,
                    "filing_date": str(filing.filing_date),
                    "fiscal_year_hint": str(filing.filing_date)[:4],
                    "sections": sorted(sections),
                    "section_chars": {k: len(v) for k, v in sections.items()},
                    "total_chars": len(text),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "file": path.name,
                }
            )
            print(
                f"  {ticker:5} {filing.accession_no}  {filing.filing_date}  "
                f"{len(text):>8,} chars  sections={sorted(sections)}"
            )
        except Exception as exc:  # noqa: BLE001 — one bad ticker must not abort the corpus
            print(f"  {ticker:5} FAILED: {type(exc).__name__}: {exc}")

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\n{len(manifest)}/{len(TICKERS)} captured -> {OUT_DIR}")
    return 0 if len(manifest) == len(TICKERS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
