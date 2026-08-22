import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from orchestrator.domain.common import CostClass
from orchestrator.domain.workers import WorkerProfile


class AppPaths(BaseModel):
    config_dir: Path
    data_dir: Path
    database: Path
    artifacts_dir: Path
    worktrees_dir: Path
    logs_dir: Path

    @classmethod
    def from_environment(cls) -> "AppPaths":
        home = Path.home()
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        config_dir = config_home / "multimodal-orchestration"
        data_dir = data_home / "multimodal-orchestration"
        return cls(
            config_dir=config_dir,
            data_dir=data_dir,
            database=data_dir / "orchestrator.db",
            artifacts_dir=data_dir / "artifacts",
            worktrees_dir=data_dir / "worktrees",
            logs_dir=data_dir / "logs",
        )


class ConfiguredWorker(BaseModel):
    id: str
    harness: str
    model: str
    capabilities: dict[str, float]
    reliability: float = Field(ge=0, le=1)
    speed: float = Field(ge=0, le=1)
    cost_class: CostClass
    parallel_capacity: int = Field(ge=1)
    context_tokens: int | None = Field(default=None, ge=1)
    tools: set[str] = Field(default_factory=set)
    can_manage: bool = False
    can_modify_repo: bool = False
    is_paid: bool = False

    def to_profile(self) -> WorkerProfile:
        return WorkerProfile(**self.model_dump())


class Settings(BaseModel):
    workers: list[ConfiguredWorker]

    @classmethod
    def load(cls, paths: AppPaths | None = None, source: Path | None = None) -> "Settings":
        paths = paths or AppPaths.from_environment()
        path = source or paths.config_dir / "workers.yaml"
        if not path.exists():
            package_default = (
                Path(__file__).resolve().parents[2] / "config" / "workers.example.yaml"
            )
            path = package_default
        payload = yaml.safe_load(path.read_text()) or {}
        return cls.model_validate(payload)
