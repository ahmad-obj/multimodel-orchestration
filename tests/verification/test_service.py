import pytest

from orchestrator.artifacts.store import ArtifactStore
from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec, TaskRisk
from orchestrator.verification.models import ReviewDecision, VerificationCheck
from orchestrator.verification.service import VerificationService
from orchestrator.workers.process import ProcessOutcome


class FakeRunner:
    def __init__(self, *, returncode=0, stdout="", stderr="", timed_out=False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.calls = []

    async def run(self, argv, *, cwd, timeout_seconds, env=None, execution_id=None):
        self.calls.append((argv, cwd, timeout_seconds))
        return ProcessOutcome(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            duration_seconds=0.01,
            timed_out=self.timed_out,
        )


class ReviewProvider:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = []

    async def review(self, *, kind, context, implementer_worker_id):
        self.calls.append((kind, context, implementer_worker_id))
        if not self.decisions:
            return None
        return self.decisions.pop(0)


def task():
    return SubtaskSpec(
        id="T1",
        objective="fix",
        capability_weights={"coding": 1},
        expected_outputs=["fix"],
        read_only=False,
        risk=TaskRisk.LOW,
        verification=[],
    )


def result(changed=None):
    return WorkerResult(
        execution_id="e",
        worker_id="w1",
        task_id="T1",
        status=ExecutionStatus.SUCCEEDED,
        summary="done",
        changed_files=changed or [],
    )


@pytest.mark.asyncio
async def test_command_failure_stores_output_artifact(tmp_path):
    service = VerificationService(ArtifactStore(tmp_path / "data"))
    workspace = tmp_path / "repo"
    workspace.mkdir()
    check = VerificationCheck(
        kind="command",
        command=["python", "-c", 'import sys;print("bad");sys.exit(2)'],
    )
    verified = await service.verify("job", task(), result(), workspace, [check])
    assert not verified.passed
    assert verified.checks[0].artifact is not None


@pytest.mark.asyncio
async def test_missing_claimed_changed_file_fails(tmp_path):
    service = VerificationService(ArtifactStore(tmp_path / "data"))
    workspace = tmp_path / "repo"
    workspace.mkdir()
    verified = await service.verify(
        "job",
        task(),
        result(["missing.py"]),
        workspace,
        [VerificationCheck(kind="changed_files")],
    )
    assert not verified.passed


@pytest.mark.asyncio
async def test_manager_rejection_fails(tmp_path):
    provider = ReviewProvider(
        [
            ReviewDecision(
                accepted=False,
                confidence=0.9,
                reasons=["bad"],
                required_followups=["fix"],
            )
        ]
    )
    service = VerificationService(
        ArtifactStore(tmp_path / "data"), review_provider=provider
    )
    workspace = tmp_path / "repo"
    workspace.mkdir()
    verified = await service.verify(
        "job",
        task(),
        result(),
        workspace,
        [VerificationCheck(kind="manager_review")],
    )
    assert not verified.passed


@pytest.mark.asyncio
async def test_review_receives_current_workspace(tmp_path):
    provider = ReviewProvider(
        [
            ReviewDecision(
                accepted=True,
                confidence=0.9,
                reasons=["ok"],
                required_followups=[],
            )
        ]
    )
    service = VerificationService(
        ArtifactStore(tmp_path / "data"), review_provider=provider
    )
    workspace = tmp_path / "current-repo"
    workspace.mkdir()

    verified = await service.verify(
        "job-1",
        task(),
        result(),
        workspace,
        [VerificationCheck(kind="manager_review")],
    )

    assert verified.passed
    assert provider.calls[0][1]["workspace"] == str(workspace)
    assert provider.calls[0][1]["job_id"] == "job-1"


@pytest.mark.asyncio
async def test_required_independent_review_unavailable_fails(tmp_path):
    service = VerificationService(ArtifactStore(tmp_path / "data"))
    workspace = tmp_path / "repo"
    workspace.mkdir()
    verified = await service.verify(
        "job",
        task(),
        result(),
        workspace,
        [VerificationCheck(kind="independent_review")],
    )
    assert not verified.passed


@pytest.mark.asyncio
async def test_repository_verification_uses_inferred_final_checks(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["pytest"]\n'
    )
    (repo / "uv.lock").write_text("")
    runner = FakeRunner(returncode=0)
    service = VerificationService(
        ArtifactStore(tmp_path / "data"), process_runner=runner
    )

    verified = await service.verify_repository("job-final", repo)

    assert verified.passed
    assert runner.calls[0][0] == ["uv", "run", "pytest", "-q"]
