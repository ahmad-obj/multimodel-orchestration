from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class TaskComplexity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskAnalysis(BaseModel):
    task_type: str
    complexity: TaskComplexity
    risk: TaskRisk
    confidence: float = Field(ge=0.0, le=1.0)
    capability_weights: dict[str, float]
    required_tools: set[str]
    repository_requirements: list[str] = Field(default_factory=list)
    context_requirements: list[str] = Field(default_factory=list)
    required_context_tokens: int | None = Field(default=None, ge=1)
    constraints: list[str]
    expected_outputs: list[str]
    parallelizable_hint: bool

    @model_validator(mode="after")
    def validate_weights(self) -> "TaskAnalysis":
        if not self.capability_weights or not any(v > 0 for v in self.capability_weights.values()):
            raise ValueError("at least one positive capability weight is required")
        if any(v < 0 or v > 1 for v in self.capability_weights.values()):
            raise ValueError("capability weights must be between 0 and 1")
        return self


class SubtaskSpec(BaseModel):
    id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    capability_weights: dict[str, float]
    dependencies: list[str] = Field(default_factory=list)
    expected_outputs: list[str]
    required_tools: set[str] = Field(default_factory=set)
    context_requirements: list[str] = Field(default_factory=list)
    write_paths: list[str] = Field(default_factory=list)
    read_only: bool
    risk: TaskRisk
    verification: list[str]
    preferred_parallel_group: str | None = None

    @model_validator(mode="after")
    def validate_subtask(self) -> "SubtaskSpec":
        if not self.expected_outputs or any(not item.strip() for item in self.expected_outputs):
            raise ValueError("expected_outputs must contain at least one non-empty item")
        if any(v < 0 or v > 1 for v in self.capability_weights.values()):
            raise ValueError("capability weights must be between 0 and 1")
        return self


class TaskPlan(BaseModel):
    goal: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    human_question: str | None = None
    subtasks: list[SubtaskSpec]
    final_expected_outputs: list[str]
