"""Narrative rail in the browser: a narrative that failed the guard is not shown as clean.

ADR-045 §3 relies on it. After a reload the rail read warnings GET did not return, so
8 of 13 stored narratives showed "grounded". The badge is checked on a fixed GET reply,
since no displayable dive may have failed (`tests/test_narrative_v2.py` covers the
API); the real-data test runs whenever one has.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from tests.test_frontend.conftest import API_BASE, BROWSER_TICKER, WEB_BASE

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


def _open_dive(page: Any, ticker: str) -> None:
    page.goto(WEB_BASE, wait_until="networkidle")
    page.get_by_role("button", name="Deep Dive").click()
    page.get_by_placeholder("NVDA").first.fill(ticker)
    page.get_by_role("button", name="Load Existing Scorecard").click()


_WARNING = "bull[0].detail: literal number '47%'"


@pytest.mark.parametrize(
    ("audit", "warnings", "badge"),
    [
        ({"status": "ok"}, [], "narrative-grounded"),
        ({"status": "guard_failed"}, [_WARNING], "narrative-guard-failed"),
        ({"status": "ok"}, [_WARNING], "narrative-guard-failed"),
        ({}, [], "narrative-guard-unknown"),
    ],
)  # fmt: skip
def test_the_badge_follows_the_stored_guard_result(
    page: Any, audit: dict[str, str], warnings: list[str], badge: str
) -> None:
    reply = {"generated": True, "run_id": 1, "one_liner": "A narrative.", "bull": [],
             "bear": [], "risks": [], "data_caveats": [], "audit": audit,
             "guard_warnings": warnings}  # fmt: skip

    def stored(route: Any) -> None:
        if route.request.method == "GET":
            route.fulfill(json=reply)
        else:
            route.continue_()

    page.route("**/dive/*/narrative", stored)
    _open_dive(page, BROWSER_TICKER)
    page.wait_for_selector(f"[data-testid={badge}]", timeout=60_000)
    others = {"narrative-grounded", "narrative-guard-failed", "narrative-guard-unknown"} - {badge}
    assert all(page.locator(f"[data-testid={b}]").count() == 0 for b in others)
    assert ("Hallucination guard warnings" in page.inner_text("body")) == bool(warnings)
    assert not page.js_errors, page.js_errors


def test_a_failed_guard_survives_a_reload(page: Any) -> None:
    ticker = _ticker_with("guard_failed")
    assert _get(f"/dive/{ticker}/narrative")["guard_warnings"]
    _open_dive(page, ticker)
    page.wait_for_selector("[data-testid=narrative-guard-failed]", timeout=60_000)
    assert page.locator("[data-testid=narrative-grounded]").count() == 0
    assert "Hallucination guard warnings" in page.inner_text("body")
    assert not page.js_errors, page.js_errors
