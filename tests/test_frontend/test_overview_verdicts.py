"""Overview verdicts in the browser (ADR-054): one vocabulary, no "Initiate".

Stored rows written before the rename still say `initiate`; the API maps them
on read. A route that forgot the mapping returned 500 while every unit test
passed, so the page itself is checked here.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest

from tests.test_frontend.conftest import API_BASE, WEB_BASE

pytestmark = pytest.mark.browser

CURRENT = {"priority_watchlist", "watchlist", "monitor", "exclude", "research_only"}


def _get(path: str) -> object:
    with urllib.request.urlopen(f"{API_BASE}{path}", timeout=30) as r:  # noqa: S310 — localhost
        return json.loads(r.read())


def test_api_serves_only_current_labels(servers_up: None) -> None:
    stats = _get("/overview/stats")
    dives = _get("/overview/recent-dives?limit=200")
    board = _get("/screener/board")
    assert isinstance(stats, dict) and isinstance(dives, list) and isinstance(board, list)
    seen = set(stats["deep_dives_30d_by_verdict"]) | {d["verdict"] for d in dives if d["verdict"]}
    seen |= {r["verdict"] for r in board if r.get("verdict")}
    assert seen <= CURRENT, f"labels outside ADR-054: {seen - CURRENT}"


def test_overview_has_no_initiate_filter(page: Any) -> None:
    page.goto(WEB_BASE, wait_until="networkidle")
    page.wait_for_selector("h3:has-text('Conviction Board')", timeout=60_000)
    filters = page.get_by_role("group", name="Filter by verdict").inner_text()
    assert "Initiate" not in filters
    assert "Watchlist" in filters
    assert "initiate" not in page.inner_text("body").lower()
    page.get_by_text("Watchlist", exact=True).click()
    page.wait_for_timeout(200)
    badges = {b.inner_text().lower() for b in page.locator("table .badge").all()}  # CSS upper-cases
    assert badges <= {"priority watchlist", "watchlist"}, badges
    assert not page.js_errors, page.js_errors
