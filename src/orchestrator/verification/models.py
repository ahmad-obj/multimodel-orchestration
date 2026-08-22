from typing import Literal

from pydantic import BaseModel, Field, model_validator

from orchestrator.domain.artifacts import ArtifactRef


class VerificationCheck(BaseModel):
    kind: Literal["command", "changed_files", "manager_review", "independent_review"]
    command: list[str] | None = None
    required: bool = True

    @model_validator(mode="after")
    def validate_command(self) -> "VerificationCheck":
        if self.kind == "command" and not self.command:
            raise ValueError("command verification requires command argv")
        return self


class CheckResult(BaseModel):
    kind: str
    passed: bool
    summary: str
    artifact: ArtifactRef | None = None


class VerificationResult(BaseModel):
    passed: bool
    checks: list[CheckResult]
    summary: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    accepted: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    required_followups: list[str]
