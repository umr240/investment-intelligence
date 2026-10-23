"""The migration chain must build exactly what the ORM declares.

This drift is invisible in normal use — an established database is already
correct — and only surfaces for someone setting up from scratch, whose very
first command fails. So it is asserted here rather than left to discovery.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from config import settings as live_settings
from data.models.schema import Base

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migrated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A database built only by `alembic upgrade head`, never by ORM metadata.

    `alembic/env.py` resolves the URL from the settings singleton, so the
    singleton is what has to be patched — setting DATABASE_URL in the
    environment is ignored once settings has been instantiated, and the
    migration would run against the real database instead.
    """
    db = tmp_path / "chain.db"
    monkeypatch.setattr(live_settings, "database_url", f"sqlite:///{db}")
    command.upgrade(Config(str(_ROOT / "alembic.ini")), "head")
    assert db.exists(), "migration did not create the temporary database"
    return db


def _reflect(db: Path) -> dict[str, set[str]]:
    con = sqlite3.connect(db)
    try:
        names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        return {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")} for t in names}
    finally:
        con.close()


def test_chain_builds_every_orm_table(migrated_db: Path) -> None:
    built = _reflect(migrated_db)
    missing = sorted(t for t in Base.metadata.tables if t not in built)
    assert not missing, f"tables declared in the ORM but never migrated: {missing}"


def test_chain_builds_every_orm_column(migrated_db: Path) -> None:
    built = _reflect(migrated_db)
    missing = sorted(
        f"{name}.{col.name}"
        for name, table in Base.metadata.tables.items()
        if name in built
        for col in table.columns
        if col.name not in built[name]
    )
    assert not missing, (
        f"{len(missing)} column(s) declared in the ORM but never migrated — a fresh "
        f"setup will fail on the first query touching one: {missing}"
    )


def test_chain_has_a_single_head() -> None:
    from alembic.script import ScriptDirectory

    heads = ScriptDirectory.from_config(Config(str(_ROOT / "alembic.ini"))).get_heads()
    assert len(heads) == 1, f"migration chain has diverged into {len(heads)} heads: {heads}"


def test_chain_matches_the_orm_exactly(migrated_db: Path) -> None:
    """Nothing extra either: an index or type the ORM lacks would drift an author DB."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrated_db}")
    try:
        with engine.connect() as con:
            diffs = compare_metadata(MigrationContext.configure(con), Base.metadata)
    finally:
        engine.dispose()
    assert not diffs, f"the migrated schema differs from the ORM: {diffs}"
