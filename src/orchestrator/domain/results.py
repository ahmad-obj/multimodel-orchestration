from pydantic import BaseModel, Field

from orchestrator.domain.artifacts import ArtifactRef
from orchestrator.domain.common import ExecutionStatus


class WorkerResult(BaseModel):
    execution_id: str
    worker_id: str
    task_id: str
    status: ExecutionStatus
    summary: str
    structured_output: dict[str, object] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    usage: dict[str, object] = Field(default_factory=dict)
    duration_seconds: float = Field(default=0.0, ge=0.0)
    errors: list[str] = Field(default_factory=list)
    local_commit: str | None = None
