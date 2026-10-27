"""
Shared pytest fixtures for investment-intelligence tests.
Uses in-memory SQLite + respx for mocking httpx calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest
import pytest_asyncio
import respx
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from data.models.schema import Base

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── requires_data gate ────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def _live_schema_present() -> bool:
    """Whether the real database has been migrated, checked once per session."""
    from data.db import engine as live_engine

    try:
        return inspect(live_engine).has_table("companies")
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _require_data(request: pytest.FixtureRequest) -> None:
    """Make `requires_data` skip on an un-migrated database, as its name implies.

    Those tests read the live DB and skip when a ticker is absent, but SQLite
    creates the file on connect — so before `invest db-init` the query fails
    with "no such table" instead of returning nothing. That read as thirteen
    failures on any fresh clone, which is the first thing a contributor runs.
    """
    if request.node.get_closest_marker("requires_data") is None:
        return
    if not request.getfixturevalue("_live_schema_present"):
        pytest.skip("database not migrated — run `invest db-init`, then a dive to populate it")


@pytest.fixture(autouse=True)
def llm_rows(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Rows the LLM-call recorder would write (ADR-048), kept in memory.

    Call sites run against fake clients in many tests; without this the recorder
    would write those calls into the real database.
    """
    import deepdive.llm_calls as llm_calls

    rows: list[dict] = []
    llm_calls._LAST.set(None)  # a previous test's call must not be annotated here

    def _capture(row: dict) -> int:
        rows.append(row)
        return len(rows)

    def _update(row_id: int, fields: dict) -> None:
        if 0 < row_id <= len(rows):
            rows[row_id - 1].update(fields)

    monkeypatch.setattr(llm_calls, "_write", _capture)
    monkeypatch.setattr(llm_calls, "_update", _update)
    return rows


# ── Database fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def engine():
    """In-memory SQLite engine for the test session."""
    eng = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def session(engine) -> Generator[Session, None, None]:
    """Per-test transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()


# ── Sample data fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sample_data() -> dict:
    """Load sample financials fixture once per session."""
    return json.loads((FIXTURES_DIR / "sample_financials.json").read_text(encoding="utf-8"))


@pytest.fixture
def nvda_income_statements(sample_data: dict) -> list[dict]:
    return sample_data["income_statements"]


@pytest.fixture
def nvda_balance_sheets(sample_data: dict) -> list[dict]:
    return sample_data["balance_sheets"]


@pytest.fixture
def nvda_cash_flows(sample_data: dict) -> list[dict]:
    return sample_data["cash_flows"]


@pytest.fixture
def nvda_profile(sample_data: dict) -> dict:
    return sample_data["company_profile"]


@pytest.fixture
def nvda_earnings_surprises(sample_data: dict) -> list[dict]:
    return sample_data["earnings_surprises"]


@pytest.fixture
def nvda_insider_transactions(sample_data: dict) -> list[dict]:
    return sample_data["insider_transactions"]


@pytest.fixture
def nvda_key_metrics(sample_data: dict) -> list[dict]:
    return sample_data["key_metrics"]


# ── HTTP mock fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def mock_fmp(sample_data: dict):
    """Mock FMP API endpoints using respx."""
    with respx.mock(assert_all_called=False) as mock:
        base = "https://financialmodelingprep.com/api/v3"

        mock.get(f"{base}/income-statement/NVDA").mock(
            return_value=respx.MockResponse(200, json=sample_data["income_statements"])
        )
        mock.get(f"{base}/balance-sheet-statement/NVDA").mock(
            return_value=respx.MockResponse(200, json=sample_data["balance_sheets"])
        )
        mock.get(f"{base}/cash-flow-statement/NVDA").mock(
            return_value=respx.MockResponse(200, json=sample_data["cash_flows"])
        )
        mock.get(f"{base}/profile/NVDA").mock(
            return_value=respx.MockResponse(200, json=[sample_data["company_profile"]])
        )
        mock.get(f"{base}/earnings-surprises/NVDA").mock(
            return_value=respx.MockResponse(200, json=sample_data["earnings_surprises"])
        )
        mock.get(f"{base}/insider-trading").mock(
            return_value=respx.MockResponse(200, json=sample_data["insider_transactions"])
        )
        mock.get(f"{base}/key-metrics/NVDA").mock(
            return_value=respx.MockResponse(200, json=sample_data["key_metrics"])
        )

        yield mock


# ── pytest-asyncio configuration ─────────────────────────────────────────────

pytest_plugins = ["pytest_asyncio"]
