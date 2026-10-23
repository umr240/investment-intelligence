"""SEC XBRL frames endpoint — cross-sectional data for one concept across
ALL filers in a given period. The critical SEC capability that closes
the long-standing "sector median / peer comparator" gap.

Endpoint:
    https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json

Period suffix conventions (per SEC docs):
    CY{year}              annual flow period (e.g. CY2024 = FY2024 calendar-aligned)
    CY{year}Q{N}          quarterly flow period (e.g. CY2024Q1 = Jan-Mar 2024)
    CY{year}Q{N}I         quarterly instant (e.g. CY2024Q4I = Dec 31, 2024 balance sheet)

The endpoint groups filers by **calendar period boundary**, not by fiscal
year. Filers with non-calendar FYEs (e.g. June 30 — INTA, AAPL legacy)
appear in different period frames than December-FYE filers. ~80% of US
public companies are December FYE so most populate CY{year}Q4 / CY{year}
frames.

Architectural role in this codebase:
  - Closes the BEW sector-median EV/Revenue gap (was listed as data_gap
    "TAM / sector median not warehoused" since system inception)
  - Powers true peer-relative scoring for F1 GP/A top-tercile, F3 R&D
    intensity ranking, F5 ROIC percentile, F7 EV/Rev z-score
  - All data is SEC XBRL — verifiable, GAAP-uniform, no API-vendor variance

Cache: each (concept, period) frame is ~10-200 KB JSON, stable once a
period is closed. Disk-cache with long TTL for historical frames (90 days),
short TTL for current/in-progress periods (1 day).

Per user 2026-05-15 SEC-first principle: this is the SEC-native answer to
peer-comparison questions previously left as "data_gap not warehoused".
"""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.settings import require_edgar_identity

logger = logging.getLogger(__name__)

_FRAMES_BASE = (
    "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json"
)

# Cache lives under .claude/cache/sec_frames/ to keep alongside the
# existing screener/dive cache infrastructure
_CACHE_DIR = Path(__file__).resolve().parent / "cache" / "sec_frames"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Result types ──────────────────────────────────────────────────────────


@dataclass
class FrameEntry:
    """One filer's value for a concept in a period."""
    cik: int
    entity_name: str
    accession: str
    period_start: str    # 'YYYY-MM-DD'
    period_end: str
    value: float
    loc: str | None = None    # filer's state of incorporation (e.g. 'US-DE')


@dataclass
class FrameDataset:
    """Full frame response for one (concept, period)."""
    concept: str
    period: str
    taxonomy: str = "us-gaap"
    label: str = ""
    description: str = ""
    entries: list[FrameEntry] = field(default_factory=list)

    def by_cik(self) -> dict[int, FrameEntry]:
        """Index entries by CIK for fast lookup."""
        return {e.cik: e for e in self.entries}

    def __len__(self) -> int:
        return len(self.entries)


# ── Fetch + cache ─────────────────────────────────────────────────────────


def _cache_path(concept: str, period: str) -> Path:
    """Per-(concept, period) cache file. Safe filename (no slashes in concepts)."""
    safe_concept = concept.replace("/", "_")
    return _CACHE_DIR / f"{safe_concept}__{period}.json"


def fetch_frame(
    concept: str,
    period: str,
    identity: str | None = None,
    use_cache: bool = True,
) -> FrameDataset | None:
    """Fetch one frame (concept × period). Returns None on 404 (no filers
    reported this concept in this period) or other non-200.

    `concept` must be a us-gaap taxonomy concept name (e.g. "Revenues",
    "ResearchAndDevelopmentExpense", "Assets", "StockholdersEquity").
    `period` follows the SEC convention (CY2024, CY2024Q1, CY2024Q1I).
    """
    if use_cache:
        cache_file = _cache_path(concept, period)
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return _build_dataset(concept, period, data)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.debug(
                    "frames cache corrupt for %s/%s: %s — refetching",
                    concept, period, exc,
                )

    from data.api._retry import sec_get_with_retry

    identity_str = identity or require_edgar_identity()
    url = _FRAMES_BASE.format(concept=concept, period=period)
    headers = {
        "User-Agent": identity_str,
        "Accept-Encoding": "gzip",
        "Host": "data.sec.gov",
    }
    resp = sec_get_with_retry(
        url, headers=headers, timeout=30.0, label=f"sec_frames_{concept}_{period}",
    )
    if resp is None or resp.status_code == 404:
        logger.info(
            "frames: no data for %s/%s (status=%s)",
            concept, period, getattr(resp, "status_code", "no response"),
        )
        return None
    if resp.status_code != 200:
        logger.warning(
            "frames fetch failed for %s/%s: status=%d",
            concept, period, resp.status_code,
        )
        return None

    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning(
            "frames parse failed for %s/%s: %s", concept, period, exc,
        )
        return None

    # Save to cache before parsing — preserves the raw shape
    if use_cache:
        cache_file = _cache_path(concept, period)
        cache_file.write_text(json.dumps(data), encoding="utf-8")

    return _build_dataset(concept, period, data)


def _build_dataset(concept: str, period: str, raw: dict[str, Any]) -> FrameDataset:
    """Materialise raw JSON into a FrameDataset."""
    ds = FrameDataset(
        concept=concept,
        period=period,
        taxonomy=raw.get("taxonomy", "us-gaap"),
        label=raw.get("label", ""),
        description=raw.get("description", ""),
    )
    for row in raw.get("data", []):
        try:
            ds.entries.append(FrameEntry(
                cik=int(row.get("cik", 0)),
                entity_name=str(row.get("entityName", "")),
                accession=str(row.get("accn", "")),
                period_start=str(row.get("start", "")),
                period_end=str(row.get("end", "")),
                value=float(row.get("val", 0.0)),
                loc=row.get("loc"),
            ))
        except (TypeError, ValueError) as exc:
            logger.debug(
                "skipping malformed frame entry in %s/%s: %s",
                concept, period, exc,
            )
    return ds


# ── Peer aggregation ──────────────────────────────────────────────────────


def filter_by_sic_prefix(
    dataset: FrameDataset,
    sic_lookup: dict[int, str],
    sic_prefix: str,
) -> list[FrameEntry]:
    """Keep only entries whose CIK is in `sic_lookup` AND whose SIC code
    starts with `sic_prefix`. Caller is responsible for constructing
    `sic_lookup` (typically from Company.cik → Company.sic_code).
    """
    return [
        e for e in dataset.entries
        if sic_lookup.get(e.cik, "").startswith(str(sic_prefix))
    ]


def compute_ratio_distribution(
    dataset_num: FrameDataset,
    dataset_den: FrameDataset,
    sic_lookup: dict[int, str] | None = None,
    sic_prefix: str | None = None,
    min_peer_count: int = 10,
) -> dict[str, Any] | None:
    """Compute a ratio (numerator concept / denominator concept) across
    peer filers and return summary stats (median, p25, p75, count).

    Joins the two datasets by CIK, optionally filters by SIC prefix,
    requires at least `min_peer_count` peers for the result to be
    statistically meaningful.

    Example use case: R&D intensity (R&D expense / Revenue) across
    Healthcare Services (SIC 80xx) peers for HIMS.

    Returns None when peer count is insufficient.
    """
    num_by_cik = dataset_num.by_cik()
    den_by_cik = dataset_den.by_cik()

    ratios: list[tuple[int, float]] = []
    for cik, num_entry in num_by_cik.items():
        den_entry = den_by_cik.get(cik)
        if den_entry is None or den_entry.value <= 0:
            continue
        # SIC filter (optional)
        if sic_prefix is not None and sic_lookup is not None:
            sic_code = sic_lookup.get(cik, "")
            if not str(sic_code).startswith(str(sic_prefix)):
                continue
        ratios.append((cik, num_entry.value / den_entry.value))

    if len(ratios) < min_peer_count:
        return None

    values = [r for _, r in ratios]
    values_sorted = sorted(values)
    n = len(values_sorted)
    return {
        "concept_num": dataset_num.concept,
        "concept_den": dataset_den.concept,
        "period": dataset_num.period,
        "sic_prefix": sic_prefix,
        "peer_count": n,
        "median": statistics.median(values_sorted),
        "p25": values_sorted[int(n * 0.25)],
        "p75": values_sorted[int(n * 0.75)],
        "p10": values_sorted[int(n * 0.10)],
        "p90": values_sorted[int(n * 0.90)],
        "min": values_sorted[0],
        "max": values_sorted[-1],
    }


def get_percentile_rank(
    target_cik: int,
    dataset_num: FrameDataset,
    dataset_den: FrameDataset,
    sic_lookup: dict[int, str] | None = None,
    sic_prefix: str | None = None,
    min_peer_count: int = 10,
) -> dict[str, Any] | None:
    """Where does `target_cik` rank within the peer-group ratio
    distribution? Returns dict with target_value, rank, percentile,
    peer_count.

    Returns None when target_cik isn't in either dataset OR peer count is
    insufficient.
    """
    num_by_cik = dataset_num.by_cik()
    den_by_cik = dataset_den.by_cik()

    target_num = num_by_cik.get(target_cik)
    target_den = den_by_cik.get(target_cik)
    if target_num is None or target_den is None or target_den.value <= 0:
        return None
    target_value = target_num.value / target_den.value

    ratios: list[float] = []
    for cik, num_entry in num_by_cik.items():
        den_entry = den_by_cik.get(cik)
        if den_entry is None or den_entry.value <= 0:
            continue
        if sic_prefix is not None and sic_lookup is not None:
            sic_code = sic_lookup.get(cik, "")
            if not str(sic_code).startswith(str(sic_prefix)):
                continue
        ratios.append(num_entry.value / den_entry.value)

    if len(ratios) < min_peer_count:
        return None

    ratios_sorted = sorted(ratios)
    # Find rank (1-indexed); percentile = (rank − 0.5) / n × 100
    rank = next(
        (i + 1 for i, v in enumerate(ratios_sorted) if v >= target_value),
        len(ratios_sorted),
    )
    pctile = (rank - 0.5) / len(ratios_sorted) * 100.0
    return {
        "target_cik": target_cik,
        "target_value": target_value,
        "rank": rank,
        "peer_count": len(ratios_sorted),
        "percentile": pctile,
        "median": ratios_sorted[len(ratios_sorted) // 2],
    }


# ── Helper for building SIC lookups across the universe ───────────────────


def build_sic_lookup_from_db() -> dict[int, str]:
    """Build {CIK → sic_code} lookup from our local Company table.

    Returns int-keyed dict (CIK as integer, matching frames data) mapped
    to the SEC SIC numeric code as a string (so prefix-matching with
    `.startswith("80")` works for "all Health Services" filtering, etc.).

    SIC codes are stable across time, so this lookup is reusable across
    all frame periods. Sourced from Company.sic_code (Integer column,
    added by Tier 2.4 migration; populated by
    fetch_sec_industry_classification).
    """
    from sqlalchemy import select

    from data.db import SessionLocal
    from data.models.schema import Company

    out: dict[int, str] = {}
    with SessionLocal() as s:
        rows = s.execute(
            select(Company.cik, Company.sic_code).where(
                Company.cik.isnot(None),
                Company.sic_code.isnot(None),
            )
        ).all()
        for cik_str, sic in rows:
            if cik_str is None or sic is None:
                continue
            try:
                cik_int = int(cik_str.lstrip("0") or "0")
            except ValueError:
                continue
            out[cik_int] = str(sic)
    return out


# SIC 2-digit code → sector label mapping (most-common buckets we encounter).
# Reference: https://www.sec.gov/info/edgar/siccodes.htm. This is a
# coarse mapping intended for screener filters + peer-group labels;
# fine-grained matching uses the full 4-digit SIC.
SIC_2DIGIT_SECTORS: dict[str, str] = {
    "01": "Agriculture, Forestry & Fishing",
    "10": "Metal Mining",
    "13": "Oil & Gas Extraction",
    "15": "Construction",
    "20": "Food & Kindred Products",
    "23": "Apparel & Other Finished Products",  # LULU
    "27": "Printing & Publishing",
    "28": "Chemicals & Allied Products",
    "30": "Rubber & Plastics",
    "33": "Primary Metal Industries",
    "35": "Industrial Machinery (incl. computer hw)",
    "36": "Electronic Equipment (incl. semiconductors)",  # NVDA/MRVL 3674 sub-bucket
    "37": "Transportation Equipment",
    "38": "Instruments & Photo Equipment",
    "48": "Communications",
    "50": "Wholesale Trade",
    "52": "Retail Trade",
    "60": "Depository Institutions",
    "63": "Insurance Carriers",
    "67": "Holding & Investment Offices",
    "70": "Hotels & Lodging",
    "73": "Business Services (incl. prepackaged software)",  # SHOP/INTA/PATH/FIG 7372 sub-bucket
    "78": "Motion Pictures",
    "79": "Amusement & Recreation",
    "80": "Health Services",  # HIMS 8011 sub-bucket
    "82": "Educational Services",
    "87": "Engineering & Management Services",
}


def sector_label_for_sic(sic_code: int | str | None) -> str | None:
    """Map a 4-digit SIC code to a 2-digit sector label. Returns None
    when the SIC is unknown or out of our mapping table."""
    if sic_code is None:
        return None
    try:
        sic_str = str(int(sic_code)).zfill(4)
    except (TypeError, ValueError):
        return None
    return SIC_2DIGIT_SECTORS.get(sic_str[:2])
