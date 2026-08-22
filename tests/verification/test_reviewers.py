from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.verification.reviewers import StructuredReviewProvider


class Adapter:
    def __init__(self):
        self.calls = []

    async def execute(self, worker, request):
        self.calls.append((worker.profile.id, request))
        return WorkerResult(
            execution_id="review",
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary="review",
            structured_output={
                "accepted": True,
                "confidence": 0.9,
                "reasons": ["ok"],
                "required_followups": [],
            },
        )


class Registry:
    def __init__(self, workers, adapter):
        self.workers = workers
        self.adapters = {"fake": adapter}

    def available(self):
        return self.workers

    def get(self, worker_id):
        return next(item for item in self.workers if item.profile.id == worker_id)


class Jobs:
    async def get(self, job_id):
        assert job_id == "job-1"
        return SimpleNamespace(manager_worker_id="manager")


def worker(worker_id: str, *, paid: bool = False, reasoning: float = 0.8):
    profile = WorkerProfile(
        id=worker_id,
        harness="fake",
        model=worker_id,
        capabilities={"reasoning": reasoning, "testing": reasoning},
        reliability=reasoning,
        speed=0.8,
        cost_class=CostClass.PAID if paid else CostClass.INCLUDED,
        parallel_capacity=1,
        tools={"filesystem"},
        is_paid=paid,
        can_manage=True,
    )
    return WorkerDescriptor(
        profile=profile,
        executable_path=Path("/fake"),
        status=WorkerStatus.AVAILABLE,
    )


@pytest.mark.asyncio
async def test_independent_review_uses_different_nonpaid_worker(tmp_path):
    adapter = Adapter()
    registry = Registry(
        [worker("implementer", reasoning=1.0), worker("reviewer", reasoning=0.9)],
        adapter,
    )
    provider = StructuredReviewProvider(registry, repo_path=tmp_path)

    decision = await provider.review(
        kind="independent_review",
        context={"objective": "review this"},
        implementer_worker_id="implementer",
    )

    assert decision is not None and decision.accepted
    assert adapter.calls[0][0] == "reviewer"


@pytest.mark.asyncio
async def test_independent_review_does_not_fall_back_to_paid_worker(tmp_path):
    adapter = Adapter()
    registry = Registry(
        [worker("implementer"), worker("paid-reviewer", paid=True, reasoning=1.0)],
        adapter,
    )
    provider = StructuredReviewProvider(registry, repo_path=tmp_path)

    decision = await provider.review(
        kind="independent_review",
        context={"objective": "review this"},
        implementer_worker_id="implementer",
    )

    assert decision is None
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_manager_review_resolves_manager_from_job_repository(tmp_path):
    adapter = Adapter()
    registry = Registry(
        [worker("implementer"), worker("manager", reasoning=0.7)],
        adapter,
    )
    provider = StructuredReviewProvider(
        registry,
        repo_path=tmp_path,
        job_repository=Jobs(),
    )

    decision = await provider.review(
        kind="manager_review",
        context={"job_id": "job-1", "objective": "review this"},
        implementer_worker_id="implementer",
    )

    assert decision is not None and decision.accepted
    assert adapter.calls[0][0] == "manager"


@pytest.mark.asyncio
async def test_review_uses_current_workspace_without_static_repo_path(tmp_path):
    adapter = Adapter()
    registry = Registry([worker("implementer"), worker("reviewer")], adapter)
    provider = StructuredReviewProvider(registry, repo_path=None)

    decision = await provider.review(
        kind="independent_review",
        context={"workspace": str(tmp_path), "objective": "review this"},
        implementer_worker_id="implementer",
    )

    assert decision is not None and decision.accepted
    assert adapter.calls[0][1].repo_path == tmp_path
