from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from orchestrator.persistence.db import Database
from orchestrator.persistence.repositories import AttemptRepository


async def test_database_initializes_sqlite_pragmas(tmp_path: Path) -> None:
    db = Database(tmp_path / "orchestrator.db")
    await db.initialize()
    async with db.engine.connect() as conn:
        fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
        jm = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        bt = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
    assert fk == 1
    assert jm == "wal"
    assert bt == 5000
    await db.dispose()


async def test_initialize_creates_v1_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "orchestrator.db")
    await db.initialize()
    expected = {
        "workers",
        "worker_profiles",
        "jobs",
        "tasks",
        "task_dependencies",
        "attempts",
        "artifacts",
        "decisions",
        "verification_runs",
        "worker_performance",
        "cost_usage",
        "events",
    }
    async with db.engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = {row[0] for row in result.fetchall()}
    assert expected <= tables
    await db.dispose()


async def test_pragmas_on_multiple_connections(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    async with db.engine.connect() as c1, db.engine.connect() as c2:
        for conn in (c1, c2):
            fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar()
            assert fk == 1
    await db.dispose()


async def test_foreign_keys_enforced(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = AttemptRepository(db)
    with pytest.raises(IntegrityError):
        await repo.start("missing-job", "t1", "w1", "exec-1")
    await db.dispose()
