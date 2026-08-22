from pydantic import BaseModel

from orchestrator.domain.workers import WorkerProfile


class CostPolicy(BaseModel):
    allow_paid: bool = False

    def permits(self, profile: WorkerProfile) -> bool:
        return self.allow_paid or not profile.is_paid
