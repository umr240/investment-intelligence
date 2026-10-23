"""Browser-test fixtures (ADR-040 §"Frontend verification is browser-driven").

These are the only tests in the suite that need live servers. Everything else
is pure or respx-mocked, and that property is worth protecting — so these
SKIP rather than fail when the servers are down, and are additionally gated
behind the ``browser`` marker.

Run them:
    uv run pytest -m browser -v

Bring the servers up first (Claude Code starts these itself per the OPERATING
CONTRACT; documented here so a human can too):
    uv run uvicorn api.app:app --host 127.0.0.1 --port 8000 \
        --reload --reload-dir api --reload-dir cli --reload-dir valuation --reload-dir data
    cd frontend && npm run dev

Note on --reload: uvicorn's WatchFiles proved unreliable in practice (it
silently missed edits to cli/skills/ during development, and a large
site-packages change put it in a state where it stopped noticing source
edits entirely). If a browser test asserts against behaviour you just changed
and fails inexplicably, restart the API before believing the failure.
"""
from __future__ import annotations

import socket

import pytest

API_HOST, API_PORT = "127.0.0.1", 8000
WEB_HOST, WEB_PORT = "localhost", 5173
API_BASE = f"http://{API_HOST}:{API_PORT}"
WEB_BASE = f"http://{WEB_HOST}:{WEB_PORT}"

# Ticker used by the valuation assertions. BONEX.ST is deliberate, not
# arbitrary: it is an ESEF-sourced (ADR-041) inflecting filer (ADR-042), so it
# exercises the hybrid-provenance path, the EPV applicability gate, the
# recent-regime EPV, AND the "withheld unusable DCF" branch in one page load.
# A US mega-cap would exercise none of those.
BROWSER_TICKER = "BONEX.ST"


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def servers_up() -> None:
    missing = []
    if not _port_open(API_HOST, API_PORT):
        missing.append(f"API {API_BASE}")
    if not _port_open(WEB_HOST, WEB_PORT):
        missing.append(f"frontend {WEB_BASE}")
    if missing:
        pytest.skip(
            "browser tests need live servers; not running: " + ", ".join(missing)
            + " — see tests/test_frontend/conftest.py for the commands"
        )


@pytest.fixture(scope="session")
def browser(servers_up):  # noqa: ANN001, ANN201
    playwright = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright not installed — `uv pip install playwright && "
               "python -m playwright install chromium`",
    )
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — browser binary not downloaded
            pytest.skip(f"chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):  # noqa: ANN001, ANN201
    """Fresh page per test, with JS errors collected into ``page.js_errors``.

    An uncaught exception or console error is a test failure in its own right —
    a React component can render a plausible-looking page while throwing, and
    every browser test here asserts the console stayed clean.
    """
    pg = browser.new_page(viewport={"width": 1600, "height": 1400})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.error: {m.text}")
          if m.type == "error" else None)
    pg.js_errors = errors  # type: ignore[attr-defined]
    yield pg
    pg.close()


@pytest.fixture
def dive_page(page):  # noqa: ANN001, ANN201
    """Deep Dive tab with BROWSER_TICKER's existing scorecard loaded.

    Uses "Load Existing Scorecard" rather than "Run Dive": reading a persisted
    scorecard is fast and deterministic, whereas a fresh dive hits SEC/ESEF and
    would make these tests slow and network-dependent for no added coverage.
    """
    page.goto(WEB_BASE, wait_until="networkidle")
    page.get_by_role("button", name="Deep Dive").click()
    page.get_by_placeholder("NVDA").first.fill(BROWSER_TICKER)
    page.get_by_role("button", name="Load Existing Scorecard").click()
    page.wait_for_selector("h3:has-text('Frameworks')", timeout=60_000)
    page.wait_for_timeout(400)
    return page
