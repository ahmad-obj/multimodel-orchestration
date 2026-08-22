from pathlib import Path

from orchestrator.domain.jobs import JobStatus
from orchestrator.persistence.db import Database
from orchestrator.persistence.job_store import JobStore


async def test_job_store_persists_selected_manager(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    store = JobStore(db)
    await store.create("j1", "task", "/tmp/repo", JobStatus.CREATED)

    await store.set_manager("j1", "codex/default")

    loaded = await store.get("j1")
    assert loaded is not None
    assert loaded.manager_worker_id == "codex/default"
    await db.dispose()


async def test_job_store_lists_recent_jobs_newest_first(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    store = JobStore(db)
    await store.create("j1", "first", "/tmp/one", JobStatus.CREATED)
    await store.create("j2", "second", "/tmp/two", JobStatus.RUNNING)

    jobs = await store.list_recent(limit=10)

    assert [job.job_id for job in jobs] == ["j2", "j1"]
    await db.dispose()
