from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from orchestrator.domain.artifacts import ArtifactRef
from orchestrator.domain.common import CostClass, WorkerStatus


class WorkerPermissions(BaseModel):
    network_allowed: bool = False
    subagents_allowed: bool = False
    allowed_shell_prefixes: list[str] = Field(default_factory=list)


class WorkerProfile(BaseModel):
    id: str
    harness: str
    model: str
    capabilities: dict[str, float]
    reliability: float = Field(ge=0.0, le=1.0)
    speed: float = Field(ge=0.0, le=1.0)
    cost_class: CostClass
    parallel_capacity: int = Field(ge=1)
    context_tokens: int | None = Field(default=None, ge=1)
    tools: set[str] = Field(default_factory=set)
    can_manage: bool = False
    can_modify_repo: bool = False
    is_paid: bool = False

    @model_validator(mode="after")
    def validate_capabilities(self) -> "WorkerProfile":
        if any(value < 0 or value > 1 for value in self.capabilities.values()):
            raise ValueError("capability scores must be between 0 and 1")
        return self


class WorkerDescriptor(BaseModel):
    profile: WorkerProfile
    executable_path: Path | None
    status: WorkerStatus
    health_reason: str | None = None


class WorkerRequest(BaseModel):
    job_id: str
    task_id: str
    objective: str
    repo_path: Path
    workspace_path: Path | None
    read_only: bool
    permissions: WorkerPermissions = Field(default_factory=WorkerPermissions)
    relevant_artifacts: list[ArtifactRef] = Field(default_factory=list)
    expected_output_schema: dict[str, object] | None = None
    timeout_seconds: int = Field(default=1800, ge=1)

    @model_validator(mode="after")
    def require_workspace_for_writes(self) -> "WorkerRequest":
        if not self.read_only and self.workspace_path is None:
            raise ValueError("modifying requests require workspace_path")
        return self
