from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile, WorkerRequest
from orchestrator.workers.gemini import GeminiAdapter


def profile() -> WorkerProfile:
    return WorkerProfile(
        id="gemini/flash",
        harness="gemini",
        model="flash",
        capabilities={"research": 0.9},
        reliability=0.8,
        speed=0.9,
        cost_class=CostClass.FREE,
        parallel_capacity=2,
        tools={"filesystem"},
        can_manage=True,
        can_modify_repo=True,
        is_paid=False,
    )


def test_gemini_command_is_headless_json(tmp_path) -> None:
    adapter = GeminiAdapter(executable=Path("/usr/bin/gemini"), model="flash")
    assert adapter.build_command(tmp_path, "inspect", model="flash") == [
        "/usr/bin/gemini",
        "-p",
        "inspect",
        "--output-format",
        "json",
        "--model",
        "flash",
    ]


async def test_gemini_execute_normalizes_fake_result(tmp_path) -> None:
    fake = tmp_path / "gemini"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'response':json.dumps({'summary':'ok','confidence':0.7,'structured_output':{'a':1}}),'stats':{'model':{'tokens':10}}}))\n"
    )
    fake.chmod(0o755)
    adapter = GeminiAdapter(executable=fake, model="auto")
    worker = WorkerDescriptor(
        profile=profile(), executable_path=fake, status=WorkerStatus.AVAILABLE
    )
    request = WorkerRequest(
        job_id="j",
        task_id="t",
        objective="inspect",
        repo_path=tmp_path,
        workspace_path=None,
        read_only=True,
        expected_output_schema={"type": "object"},
        timeout_seconds=5,
    )
    result = await adapter.execute(worker, request)
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.summary == "ok"
    assert result.structured_output == {"a": 1}
    assert result.usage == {"model": {"tokens": 10}}
