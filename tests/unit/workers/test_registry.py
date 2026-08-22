from pathlib import Path

from orchestrator.domain.common import CostClass, WorkerStatus
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.workers.base import WorkerAdapter
from orchestrator.workers.registry import WorkerRegistry


class FakeAdapter(WorkerAdapter):
    harness = "gemini"

    def __init__(self, available=True):
        self.available = available

    async def discover(self):
        p = WorkerProfile(
            id="gemini/auto",
            harness="gemini",
            model="auto",
            capabilities={},
            reliability=0.5,
            speed=0.5,
            cost_class=CostClass.FREE,
            parallel_capacity=1,
        )
        return [
            WorkerDescriptor(
                profile=p,
                executable_path=Path("/fake/gemini"),
                status=WorkerStatus.AVAILABLE if self.available else WorkerStatus.UNAVAILABLE,
            )
        ]

    async def health_check(self, worker):
        return worker

    async def execute(self, worker, request):
        raise NotImplementedError

    async def cancel(self, execution_id):
        return None


async def test_registry_excludes_unavailable_workers() -> None:
    configured = [
        WorkerProfile(
            id="gemini/flash",
            harness="gemini",
            model="flash",
            capabilities={"simple_tasks": 0.9},
            reliability=0.8,
            speed=0.9,
            cost_class=CostClass.FREE,
            parallel_capacity=2,
        ),
    ]
    registry = WorkerRegistry(configured, {"gemini": FakeAdapter(True)})
    await registry.refresh()
    assert [w.profile.id for w in registry.available()] == ["gemini/flash"]
