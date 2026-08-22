from collections.abc import Mapping

from orchestrator.domain.common import WorkerStatus
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile
from orchestrator.workers.base import WorkerAdapter


class WorkerRegistry:
    def __init__(self, configured: list[WorkerProfile], adapters: Mapping[str, WorkerAdapter]) -> None:
        self.configured = configured
        self.adapters = dict(adapters)
        self._descriptors: dict[str, WorkerDescriptor] = {}

    async def refresh(self) -> None:
        self._descriptors = {}
        by_harness: dict[str, list[WorkerProfile]] = {}
        for profile in self.configured:
            by_harness.setdefault(profile.harness, []).append(profile)
        for harness, profiles in by_harness.items():
            adapter = self.adapters.get(harness)
            if adapter is None:
                for profile in profiles:
                    self._descriptors[profile.id] = WorkerDescriptor(
                        profile=profile,
                        executable_path=None,
                        status=WorkerStatus.UNAVAILABLE,
                        health_reason=f"unknown harness: {harness}",
                    )
                continue
            discovered = await adapter.discover()
            source = discovered[0] if discovered else None
            for profile in profiles:
                if source is None:
                    descriptor = WorkerDescriptor(
                        profile=profile,
                        executable_path=None,
                        status=WorkerStatus.UNAVAILABLE,
                        health_reason="harness executable unavailable",
                    )
                else:
                    descriptor = source.model_copy(update={"profile": profile})
                self._descriptors[profile.id] = descriptor

    def available(self) -> list[WorkerDescriptor]:
        return [d for d in self._descriptors.values() if d.status is WorkerStatus.AVAILABLE]

    def all(self) -> list[WorkerDescriptor]:
        return list(self._descriptors.values())

    def get(self, worker_id: str) -> WorkerDescriptor:
        return self._descriptors[worker_id]
