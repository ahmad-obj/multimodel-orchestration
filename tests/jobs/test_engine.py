from types import SimpleNamespace

import pytest

from orchestrator.domain.events import EventType
from orchestrator.domain.jobs import JobStatus
from orchestrator.domain.tasks import (
    SubtaskSpec,
    TaskAnalysis,
    TaskComplexity,
    TaskPlan,
    TaskRisk,
)
from orchestrator.jobs.engine import JobEngine


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.events = []
        self.status = JobStatus.CREATED


class FakeEventBus:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    async def publish(self, event) -> None:
        self.recorder.events.append(event)
        self.recorder.calls.append(event.type.value)


class FakeRegistry:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    async def refresh(self) -> None:
        self.recorder.calls.append("registry.refresh")

    def all(self) -> list:
        return []


class FakeWorkerRepository:
    async def upsert_descriptor(self, worker) -> None:
        pass

    async def upsert_profile(self, profile) -> None:
        pass


class FakeJobRepository:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    async def create(self, *args, **kwargs) -> None:
        self.recorder.calls.append("job.create")
        self.recorder.status = kwargs["status"]

    async def set_status(self, job_id, status) -> None:
        self.recorder.calls.append(f"job.status:{status.value}")
        self.recorder.status = status

    async def set_manager(self, job_id, worker_id) -> None:
        self.recorder.calls.append(f"job.manager:{worker_id}")

    async def get(self, job_id):
        return SimpleNamespace(status=self.recorder.status)


class FakeTaskRepository:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    async def replace_plan(self, job_id, plan) -> None:
        self.recorder.calls.append("plan.persist")


class FakePlanning:
    def __init__(self, recorder: Recorder, paused: bool = False) -> None:
        self.recorder = recorder
        self.paused = paused

    async def plan(self, objective, summary, registry):
        self.recorder.calls.append("planning.plan")
        analysis = TaskAnalysis(
            task_type="debugging",
            complexity=TaskComplexity.HIGH,
            risk=TaskRisk.HIGH if self.paused else TaskRisk.MEDIUM,
            confidence=0.5 if self.paused else 0.9,
            capability_weights={"coding": 1.0},
            required_tools=set(),
            constraints=[],
            expected_outputs=["fix"],
            parallelizable_hint=False,
        )
        plan = TaskPlan(
            goal="fix",
            confidence=0.5 if self.paused else 0.9,
            human_question="need detail" if self.paused else None,
            subtasks=[
                SubtaskSpec(
                    id="T1",
                    objective="fix",
                    capability_weights={"coding": 1.0},
                    expected_outputs=["fix"],
                    read_only=False,
                    risk=TaskRisk.MEDIUM,
                    verification=[],
                )
            ],
            final_expected_outputs=["fix"],
        )
        return SimpleNamespace(
            analysis=analysis,
            manager_worker_id="codex/default",
            manager_selection_reason="best",
            plan=plan,
            plan_attempts=1,
            requires_human_input=self.paused,
            human_question="need detail" if self.paused else None,
        )


class FakeRuntime:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    async def run(self, job_id: str) -> None:
        self.recorder.calls.append("runtime.run")

    async def resume(self, job_id: str) -> None:
        pass

    async def cancel(self, job_id: str) -> None:
        pass


class FakeAcceptedCommits:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    async def for_job(self, job_id: str) -> dict[str, str]:
        self.recorder.calls.append("accepted.load")
        return {"T1": "abc"}


class FakeIntegration:
    def __init__(self, recorder: Recorder, workspace) -> None:
        self.recorder = recorder
        self.workspace = workspace

    async def integrate(self, **kwargs):
        self.recorder.calls.append("integration")
        return SimpleNamespace(status="succeeded", head_sha="finalsha")

    def workspace_for(self, job_id: str):
        return self.workspace


class FakeVerifier:
    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder

    async def verify_repository(self, job_id, workspace):
        self.recorder.calls.append("final.verify")
        return SimpleNamespace(passed=True)


def _engine(tmp_path, recorder: Recorder, *, paused: bool = False) -> JobEngine:
    return JobEngine(
        registry=FakeRegistry(recorder),
        worker_repository=FakeWorkerRepository(),
        job_repository=FakeJobRepository(recorder),
        task_repository=FakeTaskRepository(recorder),
        planning=FakePlanning(recorder, paused),
        runtime=FakeRuntime(recorder),
        accepted_commits=FakeAcceptedCommits(recorder),
        integration=FakeIntegration(recorder, tmp_path),
        final_verifier=FakeVerifier(recorder),
        event_bus=FakeEventBus(recorder),
        summarizer=lambda path: (
            recorder.calls.append("summarize")
            or SimpleNamespace(root=path, head_sha="base", branch="feature")
        ),
    )


@pytest.mark.asyncio
async def test_successful_job_executes_in_expected_order(tmp_path) -> None:
    recorder = Recorder()

    result = await _engine(tmp_path, recorder).run_new_job(
        tmp_path, "fix it", job_id="job-1"
    )

    assert result.status is JobStatus.COMPLETED
    assert result.final_sha == "finalsha"
    assert recorder.calls == [
        "summarize",
        "registry.refresh",
        "job.create",
        "job_created",
        "job.status:planning",
        "analysis_started",
        "planning.plan",
        "analysis_completed",
        "job.manager:codex/default",
        "manager_selected",
        "plan_created",
        "plan.persist",
        "job.status:running",
        "runtime.run",
        "accepted.load",
        "integration_started",
        "integration",
        "integration_completed",
        "final.verify",
        "job.status:completed",
        "job_completed",
    ]


@pytest.mark.asyncio
async def test_job_created_event_persists_original_repository_snapshot(tmp_path) -> None:
    recorder = Recorder()

    await _engine(tmp_path, recorder).run_new_job(tmp_path, "fix it", job_id="job-1")

    event = next(item for item in recorder.events if item.type is EventType.JOB_CREATED)
    assert event.payload == {
        "repo_path": str(tmp_path),
        "base_sha": "base",
        "branch": "feature",
    }


@pytest.mark.asyncio
async def test_high_risk_low_confidence_job_pauses_before_workers(tmp_path) -> None:
    recorder = Recorder()

    result = await _engine(tmp_path, recorder, paused=True).run_new_job(
        tmp_path, "dangerous change", job_id="job-2"
    )

    assert result.status is JobStatus.PAUSED
    assert result.human_question == "need detail"
    assert "runtime.run" not in recorder.calls
    assert "integration" not in recorder.calls
    assert recorder.calls[-2:] == ["job.status:paused", "human_input_required"]
