"""Narrative rail in the browser: a narrative that failed the guard is not shown as clean.

ADR-045 §3 relies on it. After a reload the rail read warnings GET did not return, so
8 of 13 stored narratives showed "grounded".
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from tests.test_frontend.conftest import API_BASE, WEB_BASE

pytestmark = pytest.mark.browser


def _get(path: str) -> Any:
    with urllib.request.urlopen(f"{API_BASE}{path}", timeout=30) as r:  # noqa: S310 — localhost
        return json.loads(r.read())


def _ticker_with(status: str) -> str:
    tickers: set[str] = {d["ticker"] for d in _get("/overview/recent-dives?limit=200")}
    for ticker in sorted(tickers):
        try:
            n = _get(f"/dive/{ticker}/narrative")
        except urllib.error.HTTPError:  # a dive listed without its company row
            continue
        if n.get("generated") and n.get("audit", {}).get("status") == status:
            return ticker
    pytest.skip(f"no latest dive in this DB has a {status} narrative")


def test_a_failed_guard_survives_a_reload(page: Any) -> None:
    ticker = _ticker_with("guard_failed")
    assert _get(f"/dive/{ticker}/narrative")["guard_warnings"]
    page.goto(WEB_BASE, wait_until="networkidle")
    page.get_by_role("button", name="Deep Dive").click()
    page.get_by_placeholder("NVDA").first.fill(ticker)
    page.get_by_role("button", name="Load Existing Scorecard").click()
    page.wait_for_selector("[data-testid=narrative-guard-failed]", timeout=60_000)
    assert page.locator("[data-testid=narrative-grounded]").count() == 0
    assert "Hallucination guard warnings" in page.inner_text("body")
    assert not page.js_errors, page.js_errors
