"""Sync HTTP retry helper — used by the SEC EDGAR direct call sites.

Phase 5d: previously the SEC sync clients (companyfacts, frames, universe)
issued a single ``httpx.Client.get`` and raised on any non-200 status.
SEC's fair-use cap (10 req/sec with User-Agent) is generous, but
transient 429s + 5xx + network blips would surface as hard failures
that broke a whole pipeline stage instead of being retried.

This helper provides ``sec_get_with_retry`` which:

  • Returns the ``httpx.Response`` on 200 (caller still parses).
  • On 429: sleeps for the ``retry-after`` header (or default 60s, capped
    at 90s), then retries up to ``max_attempts`` total.
  • On 5xx / network exception: exponential backoff (2 ** attempt seconds),
    retries up to ``max_attempts`` total.
  • On 4xx other than 429 (auth, 404, etc.): returns the response WITHOUT
    raising — caller handles the semantics (404 means "no companyfacts
    for this CIK" in some places, "delisted ticker" in others).
  • If retries are exhausted, returns the LAST response (or raises the
    last exception if no response was ever received). Caller is
    expected to inspect status_code.

This is sync-only by design — the existing async SEC sites
(``screener/tasks/ipo_date.py``, ``screener/tasks/fundamentals.py``)
go through the universal task runner, which already retries on
``RateLimitError``.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


_DEFAULT_RETRY_AFTER = 60.0          # seconds when no retry-after header
_RETRY_AFTER_CAP = 90.0              # never sleep more than this on 429
_MAX_ATTEMPTS = 3                    # 1 initial + 2 retries


def sec_get_with_retry(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float = 30.0,
    max_attempts: int = _MAX_ATTEMPTS,
    params: dict[str, Any] | None = None,
    label: str = "sec",
) -> httpx.Response | None:
    """Sync GET with rate-limit retry. Returns Response or None on hard failure.

    Returns:
      httpx.Response — successful 200 OR a non-retryable response (404, 403, etc.)
                       that the caller should interpret.
      None           — all retry attempts exhausted with network/transient errors.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with httpx.Client(timeout=timeout, headers=headers) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_exc = exc
            wait = 2.0 ** attempt
            logger.warning(
                "[%s] %s network error (attempt %d/%d): %s — retrying in %.1fs",
                label, url, attempt + 1, max_attempts, exc, wait,
            )
            if attempt < max_attempts - 1:
                time.sleep(wait)
            continue

        if resp.status_code == 429:
            retry_after_hdr = resp.headers.get("retry-after")
            try:
                wait = float(retry_after_hdr) if retry_after_hdr else _DEFAULT_RETRY_AFTER
            except (TypeError, ValueError):
                wait = _DEFAULT_RETRY_AFTER
            wait = min(wait, _RETRY_AFTER_CAP)
            logger.warning(
                "[%s] %s 429 rate-limited (attempt %d/%d) — sleeping %.0fs",
                label, url, attempt + 1, max_attempts, wait,
            )
            if attempt < max_attempts - 1:
                time.sleep(wait)
            continue

        if 500 <= resp.status_code < 600:
            wait = 2.0 ** attempt
            logger.warning(
                "[%s] %s status=%d (attempt %d/%d) — retrying in %.1fs",
                label, url, resp.status_code, attempt + 1, max_attempts, wait,
            )
            if attempt < max_attempts - 1:
                time.sleep(wait)
            continue

        # 2xx or non-retryable 4xx — return for caller to handle
        return resp

    logger.error(
        "[%s] %s exhausted %d attempts; last_exc=%s",
        label, url, max_attempts, last_exc,
    )
    return None


__all__ = ["sec_get_with_retry"]
