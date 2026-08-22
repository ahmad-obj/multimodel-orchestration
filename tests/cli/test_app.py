from types import SimpleNamespace

from typer.testing import CliRunner

from orchestrator.cli import app as cli
from orchestrator.domain.jobs import JobStatus


runner = CliRunner()


class FakeControl:
    async def run(self, repo_path, objective, job_id=None):
        return SimpleNamespace(
            job_id=job_id or "job-new",
            status=JobStatus.COMPLETED,
            manager_worker_id="codex/default",
            final_sha="abc123",
            human_question=None,
        )

    async def list_jobs(self, limit=50):
        return [
            SimpleNamespace(
                job_id="j1",
                status=JobStatus.RUNNING,
                manager_worker_id="codex/default",
                original_request="fix bug",
            )
        ]

    async def inspect(self, job_id):
        return SimpleNamespace(
            job=SimpleNamespace(
                job_id=job_id,
                status=JobStatus.RUNNING,
                manager_worker_id="codex/default",
                original_request="fix bug",
                repo_path="/repo",
            ),
            tasks=[SimpleNamespace(spec=SimpleNamespace(id="T1", objective="inspect"), status="running", assigned_worker_id="gemini/flash")],
            attempts=[],
            artifacts=[],
            decisions=[],
            verifications=[],
            events=[],
        )

    async def resume(self, job_id):
        return SimpleNamespace(job_id=job_id, status=JobStatus.COMPLETED, final_sha="done")

    async def cancel(self, job_id):
        return SimpleNamespace(job_id=job_id, status=JobStatus.CANCELLED)

    async def approve(self, job_id, task_id, worker_id):
        return SimpleNamespace(job_id=job_id, status=JobStatus.COMPLETED, final_sha="paid-done")

    async def reject_approval(self, job_id, task_id):
        return SimpleNamespace(job_id=job_id, status=JobStatus.FAILED)


class FakeRegistry:
    async def refresh(self):
        pass

    def all(self):
        return []


class FakeApplication:
    def __init__(self):
        self.control = FakeControl()
        self.registry = FakeRegistry()
        self.closed = False

    async def close(self):
        self.closed = True


def install_fake_app(monkeypatch):
    apps = []

    async def build():
        current = FakeApplication()
        apps.append(current)
        return current

    monkeypatch.setattr(cli, "build_application", build)
    return apps


def test_help_registers_v1_operator_commands():
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    for command in ("run", "jobs", "job", "resume", "cancel", "approve", "reject", "workers"):
        assert command in result.stdout


def test_jobs_command_uses_control_service_and_closes_application(monkeypatch):
    apps = install_fake_app(monkeypatch)

    result = runner.invoke(cli.app, ["jobs"])

    assert result.exit_code == 0
    assert "j1" in result.stdout
    assert "running" in result.stdout
    assert apps[0].closed


def test_run_command_reports_job_result(monkeypatch, tmp_path):
    apps = install_fake_app(monkeypatch)

    result = runner.invoke(cli.app, ["run", str(tmp_path), "fix the bug"])

    assert result.exit_code == 0
    assert "job-new" in result.stdout
    assert "completed" in result.stdout
    assert "abc123" in result.stdout
    assert apps[0].closed


def test_job_command_renders_task_progress(monkeypatch):
    apps = install_fake_app(monkeypatch)

    result = runner.invoke(cli.app, ["job", "j1"])

    assert result.exit_code == 0
    assert "T1" in result.stdout
    assert "gemini/flash" in result.stdout
    assert apps[0].closed


def test_approval_commands_are_explicit(monkeypatch):
    apps = install_fake_app(monkeypatch)

    approved = runner.invoke(cli.app, ["approve", "j1", "T1", "paid/frontier"])
    rejected = runner.invoke(cli.app, ["reject", "j1", "T1"])

    assert approved.exit_code == 0
    assert "completed" in approved.stdout
    assert rejected.exit_code == 0
    assert "failed" in rejected.stdout
    assert all(item.closed for item in apps)
