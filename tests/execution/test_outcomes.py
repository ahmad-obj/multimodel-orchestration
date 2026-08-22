from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.events import EventType
from orchestrator.domain.jobs import JobStatus, TaskStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.execution.failures import FailureClass
from orchestrator.execution.outcomes import OutcomeDisposition, TaskOutcomeProcessor
from orchestrator.policies.escalation import EscalationAction, EscalationActionType
from orchestrator.scheduling.scheduler import Assignment
from orchestrator.verification.models import VerificationResult


class FakeVerificationService:
    def __init__(self, passed: bool):
        self.passed = passed
        self.calls = []

    async def verify(self, *args):
        self.calls.append(args)
        return VerificationResult(
            passed=self.passed,
            checks=[],
            summary="ok" if self.passed else "failed",
        )


class FakeClassifier:
    def __init__(self, value: FailureClass):
        self.value = value

    def classify(self, **_kwargs):
        return self.value


class FakeEscalation:
    def __init__(self, action: EscalationAction):
        self.action = action
        self.calls = []

    def decide(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.action


class FakeTasks:
    def __init__(self):
        self.statuses = []
        self.assignments = []

    async def set_status(self, job_id, task_id, status):
        self.statuses.append((job_id, task_id, status))

    async def set_assignment(self, job_id, task_id, worker_id):
        self.assignments.append((job_id, task_id, worker_id))


class FakeJobs:
    def __init__(self):
        self.statuses = []

    async def set_status(self, job_id, status):
        self.statuses.append((job_id, status))


class FakeEvents:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class FakeAttempts:
    async def list_for_job(self, _job_id):
        return [SimpleNamespace(task_id="T1", worker_id="w1")]


class FakePerformance:
    def __init__(self):
        self.results = []

    async def record_outcome(self, result):
        self.results.append(result)


class FakeDecisions:
    def __init__(self):
        self.items = []

    async def append(self, job_id, task_id, kind, payload):
        self.items.append((job_id, task_id, kind, payload))


def assignment() -> Assignment:
    return Assignment(
        job_id="job-1",
        subtask=SubtaskSpec(
            id="T1",
            objective="change code",
            capability_weights={"coding": 1.0},
            expected_outputs=["working change"],
            required_tools={"filesystem", "git"},
            write_paths=["src/x.py"],
            read_only=False,
            risk=TaskRisk.LOW,
            verification=[],
        ),
        worker_id="w1",
        source_repo=Path("/repo"),
    )


def result(status=ExecutionStatus.SUCCEEDED) -> WorkerResult:
    return WorkerResult(
        execution_id="exec-1",
        worker_id="w1",
        task_id="T1",
        status=status,
        summary="done",
        changed_files=["src/x.py"],
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_verified_success_is_accepted_and_recorded():
    tasks = FakeTasks()
    events = FakeEvents()
    performance = FakePerformance()
    processor = TaskOutcomeProcessor(
        registry=SimpleNamespace(),
        verification_service=FakeVerificationService(True),
        failure_classifier=FakeClassifier(FailureClass.IMPLEMENTATION_FAILURE),
        escalation_policy=FakeEscalation(
            EscalationAction(type=EscalationActionType.STOP, reason="unused")
        ),
        task_repository=tasks,
        event_bus=events,
        performance_repository=performance,
        check_factory=lambda _task, _workspace: [],
    )

    outcome = await processor.process(assignment(), result(), Path("/workspace"))

    assert outcome.disposition is OutcomeDisposition.ACCEPTED
    assert tasks.statuses[-1] == ("job-1", "T1", TaskStatus.COMPLETED)
    assert [event.type for event in events.events] == [EventType.TASK_ACCEPTED]
    assert performance.results == [result()]


@pytest.mark.asyncio
async def test_verification_failure_retries_without_accepting():
    tasks = FakeTasks()
    events = FakeEvents()
    processor = TaskOutcomeProcessor(
        registry=SimpleNamespace(),
        verification_service=FakeVerificationService(False),
        failure_classifier=FakeClassifier(FailureClass.IMPLEMENTATION_FAILURE),
        escalation_policy=FakeEscalation(
            EscalationAction(
                type=EscalationActionType.RETRY_SAME,
                worker_id="w1",
                reason="retry",
            )
        ),
        attempt_repository=FakeAttempts(),
        task_repository=tasks,
        event_bus=events,
        check_factory=lambda _task, _workspace: [],
    )

    outcome = await processor.process(assignment(), result(), Path("/workspace"))

    assert outcome.disposition is OutcomeDisposition.RETRY
    assert tasks.assignments[-1] == ("job-1", "T1", "w1")
    assert tasks.statuses[-1] == ("job-1", "T1", TaskStatus.PENDING)
    assert EventType.TASK_ACCEPTED not in [event.type for event in events.events]
    assert EventType.TASK_REJECTED in [event.type for event in events.events]


@pytest.mark.asyncio
async def test_paid_only_escalation_pauses_job_for_approval():
    tasks = FakeTasks()
    jobs = FakeJobs()
    events = FakeEvents()
    decisions = FakeDecisions()
    processor = TaskOutcomeProcessor(
        registry=SimpleNamespace(),
        verification_service=FakeVerificationService(False),
        failure_classifier=FakeClassifier(FailureClass.INSUFFICIENT_CAPABILITY),
        escalation_policy=FakeEscalation(
            EscalationAction(
                type=EscalationActionType.REQUIRES_USER_APPROVAL,
                candidate_worker_ids=["paid/frontier"],
                reason="only paid eligible workers remain",
            )
        ),
        attempt_repository=FakeAttempts(),
        task_repository=tasks,
        job_repository=jobs,
        decision_repository=decisions,
        event_bus=events,
        check_factory=lambda _task, _workspace: [],
    )

    outcome = await processor.process(
        assignment(),
        result(ExecutionStatus.FAILED),
        Path("/workspace"),
    )

    assert outcome.disposition is OutcomeDisposition.WAITING_FOR_APPROVAL
    assert outcome.approval is not None
    assert outcome.approval.candidate_worker_ids == ["paid/frontier"]
    assert jobs.statuses[-1] == ("job-1", JobStatus.WAITING_FOR_APPROVAL)
    assert tasks.statuses[-1] == ("job-1", "T1", TaskStatus.PENDING)
    assert decisions.items[-1][2] == "paid_escalation_approval_request"
    assert events.events[-1].type is EventType.APPROVAL_REQUIRED
