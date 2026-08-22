from types import SimpleNamespace

import pytest

from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.jobs.service import JobControlService


class Jobs:
    def __init__(self, status=JobStatus.RUNNING):
        self.status = status
        self.statuses = []

    async def list_recent(self, limit=50):
        return [SimpleNamespace(job_id="j1", status=self.status)]

    async def get(self, job_id):
        return SimpleNamespace(job_id=job_id, status=self.status)

    async def set_status(self, job_id, status):
        self.status = status
        self.statuses.append((job_id, status))


class Repo:
    async def list_for_job(self, job_id):
        return [SimpleNamespace(job_id=job_id)]


class Tasks(Repo):
    def __init__(self):
        self.assignments = []
        self.statuses = []

    async def set_assignment(self, job_id, task_id, worker_id):
        self.assignments.append((job_id, task_id, worker_id))

    async def set_status(self, job_id, task_id, status):
        self.statuses.append((job_id, task_id, status))


class Decisions(Repo):
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.appended = []

    async def list_for_job(self, job_id):
        return list(self.rows)

    async def append(self, job_id, task_id, decision_type, payload):
        self.appended.append((job_id, task_id, decision_type, payload))


class Engine:
    def __init__(self):
        self.resumed = []

    async def run_new_job(self, repo_path, objective, job_id=None):
        return SimpleNamespace(job_id=job_id or "generated", status=JobStatus.COMPLETED)

    async def resume_job(self, job_id):
        self.resumed.append(job_id)
        return SimpleNamespace(job_id=job_id, status=JobStatus.COMPLETED)


class Runtime:
    def __init__(self):
        self.cancelled = []

    async def cancel(self, job_id):
        self.cancelled.append(job_id)


def service(*, jobs=None, tasks=None, decisions=None, engine=None, runtime=None):
    return JobControlService(
        jobs=jobs or Jobs(),
        tasks=tasks or Repo(),
        attempts=Repo(),
        artifacts=Repo(),
        decisions=decisions or Repo(),
        verifications=Repo(),
        events=Repo(),
        engine=engine or Engine(),
        runtime=runtime or Runtime(),
    )


@pytest.mark.asyncio
async def test_job_control_inspection_collects_durable_views():
    snapshot = await service().inspect("j1")

    assert snapshot.job.job_id == "j1"
    assert len(snapshot.tasks) == 1
    assert len(snapshot.attempts) == 1
    assert len(snapshot.events) == 1


@pytest.mark.asyncio
async def test_job_control_delegates_resume_and_cancel():
    runtime = Runtime()
    control = service(runtime=runtime)

    resumed = await control.resume("j1")
    cancelled = await control.cancel("j1")

    assert resumed.status is JobStatus.COMPLETED
    assert cancelled.status is JobStatus.RUNNING
    assert runtime.cancelled == ["j1"]


@pytest.mark.asyncio
async def test_approve_paid_escalation_is_scoped_to_requested_task():
    jobs = Jobs(JobStatus.WAITING_FOR_APPROVAL)
    tasks = Tasks()
    engine = Engine()
    decisions = Decisions(
        [
            SimpleNamespace(
                task_id="T1",
                decision_type="paid_escalation_approval_request",
                payload={
                    "id": "approval-1",
                    "job_id": "j1",
                    "task_id": "T1",
                    "reason": "only paid worker remains",
                    "candidate_worker_ids": ["paid/frontier", "paid/other"],
                    "status": "pending",
                },
            )
        ]
    )
    control = service(jobs=jobs, tasks=tasks, decisions=decisions, engine=engine)

    result = await control.approve("j1", "T1", "paid/frontier")

    assert tasks.assignments == [("j1", "T1", "paid/frontier")]
    assert tasks.statuses == [("j1", "T1", TaskStatus.READY)]
    assert jobs.statuses == [("j1", JobStatus.RUNNING)]
    assert decisions.appended[-1][2] == "paid_escalation_approved"
    assert decisions.appended[-1][3]["worker_id"] == "paid/frontier"
    assert engine.resumed == ["j1"]
    assert result.status is JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_approval_rejects_worker_outside_candidate_set():
    jobs = Jobs(JobStatus.WAITING_FOR_APPROVAL)
    decisions = Decisions(
        [
            SimpleNamespace(
                task_id="T1",
                decision_type="paid_escalation_approval_request",
                payload={
                    "id": "approval-1",
                    "job_id": "j1",
                    "task_id": "T1",
                    "reason": "paid required",
                    "candidate_worker_ids": ["paid/frontier"],
                    "status": "pending",
                },
            )
        ]
    )
    control = service(jobs=jobs, tasks=Tasks(), decisions=decisions)

    with pytest.raises(ValueError, match="not an approved candidate"):
        await control.approve("j1", "T1", "paid/not-offered")


@pytest.mark.asyncio
async def test_reject_paid_escalation_stops_task_and_job():
    jobs = Jobs(JobStatus.WAITING_FOR_APPROVAL)
    tasks = Tasks()
    engine = Engine()
    decisions = Decisions(
        [
            SimpleNamespace(
                task_id="T1",
                decision_type="paid_escalation_approval_request",
                payload={
                    "id": "approval-1",
                    "job_id": "j1",
                    "task_id": "T1",
                    "reason": "paid required",
                    "candidate_worker_ids": ["paid/frontier"],
                    "status": "pending",
                },
            )
        ]
    )
    control = service(jobs=jobs, tasks=tasks, decisions=decisions, engine=engine)

    rejected = await control.reject_approval("j1", "T1")

    assert tasks.statuses == [("j1", "T1", TaskStatus.FAILED)]
    assert jobs.statuses == [("j1", JobStatus.FAILED)]
    assert decisions.appended[-1][2] == "paid_escalation_rejected"
    assert engine.resumed == []
    assert rejected.status is JobStatus.FAILED
