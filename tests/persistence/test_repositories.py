from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.domain.artifacts import ArtifactRef
from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskPlan, TaskRisk
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.persistence.db import Database
from orchestrator.persistence.repositories import (
    ArtifactRepository,
    AttemptRepository,
    CostUsageRepository,
    DecisionRepository,
    EventRepository,
    JobRepository,
    TaskRepository,
    VerificationRepository,
    WorkerPerformanceRepository,
    WorkerRepository,
)


def make_profile(worker_id: str = "codex-main") -> WorkerProfile:
    return WorkerProfile(
        id=worker_id,
        harness="codex",
        model="gpt-5-codex",
        capabilities={"coding": 0.9, "debugging": 0.8},
        reliability=0.95,
        speed=0.7,
        cost_class=CostClass.INCLUDED,
        parallel_capacity=2,
        context_tokens=200_000,
        tools={"shell", "filesystem"},
        can_manage=True,
        can_modify_repo=True,
    )


def make_descriptor(worker_id: str = "codex-main") -> WorkerDescriptor:
    return WorkerDescriptor(
        profile=make_profile(worker_id),
        executable_path=Path("/usr/bin/codex"),
        status=WorkerStatus.AVAILABLE,
        health_reason=None,
    )


def make_plan() -> TaskPlan:
    return TaskPlan(
        goal="Implement feature X",
        confidence=0.85,
        subtasks=[
            SubtaskSpec(
                id="inspect",
                objective="Inspect the repo",
                capability_weights={"repo_navigation": 0.9},
                dependencies=[],
                expected_outputs=["repo structure"],
                required_tools={"filesystem"},
                context_requirements=["repository tree"],
                write_paths=[],
                read_only=True,
                risk=TaskRisk.LOW,
                verification=["manager_review"],
            ),
            SubtaskSpec(
                id="implement",
                objective="Implement the feature",
                capability_weights={"coding": 0.9},
                dependencies=["inspect"],
                expected_outputs=["source files"],
                required_tools={"shell"},
                context_requirements=["repo structure"],
                write_paths=["src/"],
                read_only=False,
                risk=TaskRisk.MEDIUM,
                verification=["tests_pass"],
            ),
        ],
        final_expected_outputs=["feature X complete"],
    )


async def test_worker_descriptor_upsert(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = WorkerRepository(db)
    desc = make_descriptor("w1")
    await repo.upsert_descriptor(desc)
    await repo.upsert_profile(make_profile("w1"))
    loaded = await repo.get_descriptor("w1")
    assert loaded is not None
    assert loaded.profile.id == "w1"
    assert loaded.status == WorkerStatus.AVAILABLE
    assert loaded.executable_path == Path("/usr/bin/codex")
    await db.dispose()


async def test_worker_profile_upsert(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = WorkerRepository(db)
    profile = make_profile("w1")
    await repo.upsert_profile(profile)
    loaded = await repo.get_profile("w1")
    assert loaded is not None
    assert loaded.id == "w1"
    assert loaded.capabilities == {"coding": 0.9, "debugging": 0.8}
    await db.dispose()


async def test_worker_upsert_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = WorkerRepository(db)
    desc = make_descriptor("w1")
    await repo.upsert_descriptor(desc)
    await repo.upsert_profile(make_profile("w1"))
    await repo.upsert_descriptor(desc)
    await repo.upsert_profile(make_profile("w1"))
    loaded = await repo.get_descriptor("w1")
    assert loaded is not None
    await db.dispose()


async def test_worker_profile_update(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = WorkerRepository(db)
    p1 = make_profile("w1")
    await repo.upsert_profile(p1)
    p2 = make_profile("w1")
    p2.reliability = 0.5
    await repo.upsert_profile(p2)
    loaded = await repo.get_profile("w1")
    assert loaded is not None
    assert loaded.reliability == 0.5
    await db.dispose()


async def test_worker_descriptor_none_for_unknown(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = WorkerRepository(db)
    assert await repo.get_descriptor("nobody") is None
    assert await repo.get_profile("nobody") is None
    await db.dispose()


async def test_worker_descriptor_without_profile(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = WorkerRepository(db)
    await repo.upsert_descriptor(make_descriptor("w1"))
    assert await repo.get_descriptor("w1") is None
    await db.dispose()


async def test_job_create_and_get(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = JobRepository(db)
    job = await repo.create("j1", "implement feature X", "/tmp/repo", JobStatus.CREATED)
    assert job.job_id == "j1"
    assert job.status == JobStatus.CREATED
    loaded = await repo.get("j1")
    assert loaded is not None
    assert loaded.original_request == "implement feature X"
    assert loaded.repo_path == "/tmp/repo"
    assert loaded.manager_worker_id is None
    await db.dispose()


async def test_job_create_with_manager(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = JobRepository(db)
    await repo.create("j1", "x", "/tmp", JobStatus.CREATED, manager_worker_id="mgr-1")
    loaded = await repo.get("j1")
    assert loaded is not None
    assert loaded.manager_worker_id == "mgr-1"
    await db.dispose()


async def test_job_set_status(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = JobRepository(db)
    await repo.create("j1", "r", "/tmp", JobStatus.CREATED)
    await repo.set_status("j1", JobStatus.RUNNING)
    loaded = await repo.get("j1")
    assert loaded is not None
    assert loaded.status == JobStatus.RUNNING
    await db.dispose()


async def test_job_set_status_unknown_raises(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    repo = JobRepository(db)
    with pytest.raises(ValueError, match="not found"):
        await repo.set_status("nope", JobStatus.FAILED)
    await db.dispose()


async def test_job_get_unknown_returns_none(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    assert await JobRepository(db).get("none") is None
    await db.dispose()


async def test_task_plan_persist_and_restore(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    task_repo = TaskRepository(db)
    await task_repo.replace_plan("j1", make_plan())
    tasks = await task_repo.list_for_job("j1")
    assert len(tasks) == 2
    assert tasks[0].spec.id == "inspect"
    assert tasks[0].position == 0
    assert tasks[0].status == TaskStatus.PENDING
    assert tasks[1].spec.id == "implement"
    assert tasks[1].spec.dependencies == ["inspect"]
    assert tasks[1].position == 1
    await db.dispose()


async def test_task_dependencies_persist(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    await TaskRepository(db).replace_plan("j1", make_plan())
    async with db.engine.connect() as conn:
        from sqlalchemy import text

        result = await conn.execute(
            text("SELECT depends_on_task_id FROM task_dependencies WHERE job_id='j1'")
        )
        deps = [row[0] for row in result.fetchall()]
    assert deps == ["inspect"]
    await db.dispose()


async def test_task_assignment_persists(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    task_repo = TaskRepository(db)
    await task_repo.replace_plan("j1", make_plan())
    await task_repo.set_assignment("j1", "implement", "codex-main")
    tasks = await task_repo.list_for_job("j1")
    impl = [t for t in tasks if t.spec.id == "implement"][0]
    assert impl.assigned_worker_id == "codex-main"
    await db.dispose()


async def test_task_status_persists(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    task_repo = TaskRepository(db)
    await task_repo.replace_plan("j1", make_plan())
    await task_repo.set_status("j1", "inspect", TaskStatus.RUNNING)
    tasks = await task_repo.list_for_job("j1")
    insp = [t for t in tasks if t.spec.id == "inspect"][0]
    assert insp.status == TaskStatus.RUNNING
    await db.dispose()


async def test_task_set_assignment_unknown_raises(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    await TaskRepository(db).replace_plan("j1", make_plan())
    with pytest.raises(ValueError, match="not found"):
        await TaskRepository(db).set_assignment("j1", "nope", "w1")
    await db.dispose()


async def test_task_set_status_unknown_raises(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    with pytest.raises(ValueError, match="not found"):
        await TaskRepository(db).set_status("j1", "nope", TaskStatus.RUNNING)
    await db.dispose()


async def test_replace_plan_clears_existing(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    task_repo = TaskRepository(db)
    await task_repo.replace_plan("j1", make_plan())
    assert len(await task_repo.list_for_job("j1")) == 2
    new_plan = TaskPlan(
        goal="simplified",
        confidence=0.5,
        subtasks=[
            SubtaskSpec(
                id="only-one",
                objective="do it",
                capability_weights={"coding": 1.0},
                dependencies=[],
                expected_outputs=["result"],
                required_tools=set(),
                context_requirements=[],
                write_paths=[],
                read_only=False,
                risk=TaskRisk.LOW,
                verification=[],
            )
        ],
        final_expected_outputs=["done"],
    )
    await task_repo.replace_plan("j1", new_plan)
    tasks = await task_repo.list_for_job("j1")
    assert len(tasks) == 1
    assert tasks[0].spec.id == "only-one"
    await db.dispose()


# ── Attempt repository ──────────────────────────────────────────────────


async def test_attempt_start_and_finish(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = AttemptRepository(db)
    eid = await repo.start("j1", "t1", "w1", "exec-1")
    assert eid == "exec-1"
    attempt = await repo.get("exec-1")
    assert attempt is not None
    assert attempt.status is None
    assert attempt.started_at is not None
    await repo.finish("exec-1", ExecutionStatus.SUCCEEDED, result_json='{"ok":true}')
    attempt = await repo.get("exec-1")
    assert attempt is not None
    assert attempt.status == ExecutionStatus.SUCCEEDED
    assert attempt.result_json == '{"ok":true}'
    assert attempt.finished_at is not None
    await db.dispose()


async def test_attempt_finish_with_failure(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = AttemptRepository(db)
    await repo.start("j1", "t1", "w1", "exec-1")
    await repo.finish("exec-1", ExecutionStatus.FAILED, failure_class="timeout")
    attempt = await repo.get("exec-1")
    assert attempt is not None
    assert attempt.status == ExecutionStatus.FAILED
    assert attempt.failure_class == "timeout"
    await db.dispose()


async def test_attempt_finish_unknown_raises(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    with pytest.raises(ValueError, match="not found"):
        await AttemptRepository(db).finish("nope", ExecutionStatus.FAILED)
    await db.dispose()


async def test_attempt_list_for_job(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = AttemptRepository(db)
    await repo.start("j1", "t1", "w1", "e1")
    await repo.start("j1", "t1", "w1", "e2")
    attempts = await repo.list_for_job("j1")
    assert len(attempts) == 2
    assert attempts[0].execution_id == "e1"
    assert attempts[1].execution_id == "e2"
    await db.dispose()


# ── Artifact repository ─────────────────────────────────────────────────


async def test_artifact_record_and_list(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = ArtifactRepository(db)
    ref = ArtifactRef(uri="artifact://j1/t1/report.json")
    stored = await repo.record("j1", "t1", ref, {"format": "json", "lines": 42})
    assert stored.artifact_ref == ref
    assert stored.metadata == {"format": "json", "lines": 42}
    items = await repo.list_for_job("j1")
    assert len(items) == 1
    assert items[0].artifact_ref.uri == "artifact://j1/t1/report.json"
    assert items[0].metadata == {"format": "json", "lines": 42}
    await db.dispose()


# ── Decision repository ─────────────────────────────────────────────────


async def test_decision_append_and_list(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = DecisionRepository(db)
    payload = {"manager": "mgr-1", "scores": [0.9, 0.8], "nested": {"a": [1, 2]}}
    stored = await repo.append("j1", "t1", "manager_selection", payload)
    assert stored.decision_type == "manager_selection"
    assert stored.payload == payload
    items = await repo.list_for_job("j1")
    assert len(items) == 1
    assert items[0].payload["nested"]["a"] == [1, 2]
    await db.dispose()


async def test_decision_preserves_structured_payload(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = DecisionRepository(db)
    payload = {
        "routing": {"scores": {"coding": 0.95, "debugging": 0.7}},
        "reason": "best match",
        "flag": True,
        "count": 3,
    }
    await repo.append("j1", "t1", "routing", payload)
    items = await repo.list_for_job("j1")
    assert items[0].payload == payload
    await db.dispose()


async def test_decision_with_null_task(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = DecisionRepository(db)
    stored = await repo.append("j1", None, "job_level_decision", {"action": "proceed"})
    assert stored.task_id is None
    items = await repo.list_for_job("j1")
    assert items[0].task_id is None
    await db.dispose()


# ── Verification repository ─────────────────────────────────────────────


async def test_verification_record_and_list(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = VerificationRepository(db)
    vjson = '{"passed": true, "checks": ["lint", "tests"]}'
    stored = await repo.record("j1", "t1", vjson)
    assert stored.verification_json == vjson
    items = await repo.list_for_job("j1")
    assert len(items) == 1
    assert items[0].verification_json == vjson
    await db.dispose()


# ── Cost usage repository ───────────────────────────────────────────────


async def test_cost_usage_record_and_list(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = CostUsageRepository(db)
    ujson = '{"tokens_in": 1000, "tokens_out": 500, "cost_usd": 0.02}'
    stored = await repo.record("j1", "t1", "w1", ujson)
    assert stored.usage_json == ujson
    assert stored.worker_id == "w1"
    items = await repo.list_for_job("j1")
    assert len(items) == 1
    assert items[0].usage_json == ujson
    await db.dispose()


# ── Event repository ────────────────────────────────────────────────────


async def test_events_maintain_job_ordering(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    await JobRepository(db).create("j2", "r2", "/tmp2", JobStatus.CREATED)
    repo = EventRepository(db)
    e1 = OrchestratorEvent(type=EventType.JOB_CREATED, job_id="j1")
    e2 = OrchestratorEvent(type=EventType.MANAGER_SELECTED, job_id="j1", worker_id="mgr")
    e3 = OrchestratorEvent(type=EventType.JOB_CREATED, job_id="j2")
    await repo.append(e1)
    await repo.append(e2)
    await repo.append(e3)
    j1_events = await repo.list_for_job("j1")
    assert len(j1_events) == 2
    assert j1_events[0].type == EventType.JOB_CREATED
    assert j1_events[1].type == EventType.MANAGER_SELECTED
    j2_events = await repo.list_for_job("j2")
    assert len(j2_events) == 1
    await db.dispose()


async def test_events_round_trip_domain_model(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = EventRepository(db)
    original = OrchestratorEvent(
        type=EventType.WORKER_COMPLETED,
        job_id="j1",
        task_id="t1",
        worker_id="w1",
        payload={"summary": "done", "count": 5},
    )
    await repo.append(original)
    events = await repo.list_for_job("j1")
    loaded = events[0]
    assert loaded.type == original.type
    assert loaded.job_id == original.job_id
    assert loaded.task_id == original.task_id
    assert loaded.worker_id == original.worker_id
    assert loaded.payload == original.payload
    await db.dispose()


# ── Worker performance repository ───────────────────────────────────────


async def test_worker_performance_record_and_list(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    await db.initialize()
    await JobRepository(db).create("j1", "r", "/tmp", JobStatus.CREATED)
    repo = WorkerPerformanceRepository(db)
    outcome = WorkerResult(
        execution_id="exec-1",
        worker_id="w1",
        task_id="t1",
        status=ExecutionStatus.SUCCEEDED,
        summary="done",
        confidence=0.95,
        duration_seconds=12.5,
        usage={"tokens": 1000},
    )
    stored = await repo.record_outcome(outcome)
    assert stored.execution_id == "exec-1"
    assert stored.confidence == 0.95
    assert stored.usage == {"tokens": 1000}
    items = await repo.list_for_worker("w1")
    assert len(items) == 1
    assert items[0].status == ExecutionStatus.SUCCEEDED
    await db.dispose()


# ── Close DB and reopen ─────────────────────────────────────────────────


async def test_data_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    db1 = Database(path)
    await db1.initialize()

    await WorkerRepository(db1).upsert_descriptor(make_descriptor("w1"))
    await WorkerRepository(db1).upsert_profile(make_profile("w1"))
    await JobRepository(db1).create("j1", "request", "/repo", JobStatus.RUNNING)
    await TaskRepository(db1).replace_plan("j1", make_plan())
    await TaskRepository(db1).set_assignment("j1", "inspect", "w1")
    await TaskRepository(db1).set_status("j1", "inspect", TaskStatus.COMPLETED)
    await AttemptRepository(db1).start("j1", "t1", "w1", "e1")
    await AttemptRepository(db1).finish("e1", ExecutionStatus.SUCCEEDED, result_json="{}")
    ref = ArtifactRef(uri="artifact://j1/t1/out.txt")
    await ArtifactRepository(db1).record("j1", "t1", ref, {"k": "v"})
    await DecisionRepository(db1).append("j1", "t1", "routing", {"score": 0.9})
    await VerificationRepository(db1).record("j1", "t1", '{"passed":true}')
    await CostUsageRepository(db1).record("j1", "t1", "w1", '{"cost":0.01}')
    await EventRepository(db1).append(OrchestratorEvent(type=EventType.JOB_CREATED, job_id="j1"))
    outcome = WorkerResult(
        execution_id="e1",
        worker_id="w1",
        task_id="t1",
        status=ExecutionStatus.SUCCEEDED,
        summary="ok",
        confidence=0.9,
    )
    await WorkerPerformanceRepository(db1).record_outcome(outcome)
    await db1.dispose()

    db2 = Database(path)
    await db2.initialize()

    assert await WorkerRepository(db2).get_profile("w1") is not None
    assert await WorkerRepository(db2).get_descriptor("w1") is not None
    job = await JobRepository(db2).get("j1")
    assert job is not None
    assert job.status == JobStatus.RUNNING
    tasks = await TaskRepository(db2).list_for_job("j1")
    assert len(tasks) == 2
    attempts = await AttemptRepository(db2).list_for_job("j1")
    assert len(attempts) == 1
    assert attempts[0].status == ExecutionStatus.SUCCEEDED
    artifacts = await ArtifactRepository(db2).list_for_job("j1")
    assert len(artifacts) == 1
    decisions = await DecisionRepository(db2).list_for_job("j1")
    assert len(decisions) == 1
    assert decisions[0].payload == {"score": 0.9}
    verifs = await VerificationRepository(db2).list_for_job("j1")
    assert len(verifs) == 1
    costs = await CostUsageRepository(db2).list_for_job("j1")
    assert len(costs) == 1
    events = await EventRepository(db2).list_for_job("j1")
    assert len(events) == 1
    perf = await WorkerPerformanceRepository(db2).list_for_worker("w1")
    assert len(perf) == 1

    await db2.dispose()
