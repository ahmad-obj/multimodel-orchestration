import json
from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.workers import (
    WorkerDescriptor,
    WorkerPermissions,
    WorkerProfile,
    WorkerRequest,
)
from orchestrator.workers.opencode import OpenCodeAdapter


def profile() -> WorkerProfile:
    return WorkerProfile(
        id="opencode/deepseek/deepseek-chat",
        harness="opencode",
        model="deepseek/deepseek-chat",
        capabilities={"coding": 0.8},
        reliability=0.75,
        speed=0.7,
        cost_class=CostClass.FREE,
        parallel_capacity=2,
        tools={"filesystem", "shell", "git"},
        can_manage=True,
        can_modify_repo=True,
        is_paid=False,
    )


def request(tmp_path) -> WorkerRequest:
    return WorkerRequest(
        job_id="j",
        task_id="t",
        objective="inspect",
        repo_path=tmp_path,
        workspace_path=None,
        read_only=True,
        permissions=WorkerPermissions(
            network_allowed=False,
            subagents_allowed=False,
            allowed_shell_prefixes=["git status"],
        ),
        expected_output_schema={"type": "object"},
        timeout_seconds=5,
    )


def test_opencode_command_selects_model_and_json(tmp_path) -> None:
    adapter = OpenCodeAdapter(Path("/usr/bin/opencode"), "deepseek/deepseek-chat")
    assert adapter.build_command(tmp_path, "inspect", model="deepseek/deepseek-chat") == [
        "/usr/bin/opencode",
        "run",
        "inspect",
        "--model",
        "deepseek/deepseek-chat",
        "--format",
        "json",
        "--dir",
        str(tmp_path),
    ]


def test_opencode_config_denies_network_subagents_and_external_paths(tmp_path) -> None:
    adapter = OpenCodeAdapter(Path("/usr/bin/opencode"), "deepseek/deepseek-chat")
    config = json.loads(adapter._config_content(request(tmp_path)))
    permission = config["permission"]

    assert permission["edit"] == "deny"
    assert permission["task"] == "deny"
    assert permission["webfetch"] == "deny"
    assert permission["websearch"] == "deny"
    assert permission["external_directory"] == "deny"
    assert permission["bash"]["*"] == "deny"
    assert permission["bash"]["git status*"] == "allow"
    assert permission["bash"]["git push*"] == "deny"


async def test_opencode_execute_normalizes_jsonl(tmp_path) -> None:
    fake = tmp_path / "opencode"
    payload = json.dumps({"summary": "ok", "confidence": 0.75, "structured_output": {"k": "v"}})
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        f"print(json.dumps({{'type':'message','role':'assistant','content':{payload!r}}}))\n"
        "print(json.dumps({'type':'unknown.future.event','foo':1}))\n"
    )
    fake.chmod(0o755)
    adapter = OpenCodeAdapter(fake, "deepseek/deepseek-chat")
    worker = WorkerDescriptor(
        profile=profile(), executable_path=fake, status=WorkerStatus.AVAILABLE
    )
    result = await adapter.execute(worker, request(tmp_path))
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.summary == "ok"
    assert result.structured_output == {"k": "v"}
    assert result.usage["unknown_events"][0]["type"] == "unknown.future.event"
