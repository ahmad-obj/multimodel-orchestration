from pathlib import Path

from orchestrator.bootstrap import OrchestratorApplication, build_application
from orchestrator.config import AppPaths, ConfiguredWorker, Settings
from orchestrator.domain.common import CostClass
from orchestrator.persistence.job_store import JobStore


class Adapter:
    harness = "fake"


def paths(tmp_path: Path) -> AppPaths:
    data = tmp_path / "data"
    return AppPaths(
        config_dir=tmp_path / "config",
        data_dir=data,
        database=data / "orchestrator.db",
        artifacts_dir=data / "artifacts",
        worktrees_dir=data / "worktrees",
        logs_dir=data / "logs",
    )


def settings() -> Settings:
    return Settings(
        workers=[
            ConfiguredWorker(
                id="fake/model",
                harness="fake",
                model="model",
                capabilities={"coding": 0.8, "reasoning": 0.8, "simple_tasks": 0.9},
                reliability=0.8,
                speed=0.8,
                cost_class=CostClass.FREE,
                parallel_capacity=1,
                tools={"filesystem", "git"},
                can_manage=True,
                can_modify_repo=True,
            )
        ]
    )


async def test_build_application_wires_one_shared_durable_system(tmp_path: Path) -> None:
    app = await build_application(
        paths=paths(tmp_path),
        settings=settings(),
        adapters={"fake": Adapter()},
    )

    assert isinstance(app, OrchestratorApplication)
    assert isinstance(app.jobs, JobStore)
    assert app.database.path == tmp_path / "data" / "orchestrator.db"
    assert app.engine.job_repository is app.jobs
    assert app.runtime._jobs is app.jobs
    assert app.registry.configured[0].id == "fake/model"

    await app.close()
