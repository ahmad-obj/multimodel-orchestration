from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.workers import (
    WorkerDescriptor,
    WorkerPermissions,
    WorkerProfile,
    WorkerRequest,
)
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


def request(tmp_path, *, read_only: bool = True) -> WorkerRequest:
    return WorkerRequest(
        job_id="j",
        task_id="t",
        objective="inspect",
        repo_path=tmp_path,
        workspace_path=None if read_only else tmp_path,
        read_only=read_only,
        permissions=WorkerPermissions(
            network_allowed=False,
            subagents_allowed=False,
            allowed_shell_prefixes=["git status", "uv run pytest"],
        ),
        expected_output_schema={"type": "object"},
        timeout_seconds=5,
    )


def test_gemini_command_is_headless_json_with_policy(tmp_path) -> None:
    adapter = GeminiAdapter(executable=Path("/usr/bin/gemini"), model="flash")
    policy_path = tmp_path / "policy.toml"
    assert adapter.build_command(
        tmp_path,
        "inspect",
        model="flash",
        approval_mode="plan",
        policy_path=policy_path,
    ) == [
        "/usr/bin/gemini",
        "-p",
        "inspect",
        "--output-format",
        "json",
        "--model",
        "flash",
        "--approval-mode",
        "plan",
        "--policy",
        str(policy_path),
    ]


def test_gemini_policy_fails_closed_and_allows_only_requested_actions(tmp_path) -> None:
    adapter = GeminiAdapter(executable=Path("/usr/bin/gemini"), model="flash")
    policy = adapter._policy_content(request(tmp_path, read_only=False))

    assert 'toolName = "*"' in policy
    assert 'decision = "deny"' in policy
    assert 'toolName = ["glob", "grep_search", "list_directory", "read_file", "read_many_files"]' in policy
    assert 'toolName = ["replace", "write_file"]' in policy
    assert 'commandPrefix = "git status"' in policy
    assert 'commandPrefix = "uv run pytest"' in policy
    assert "google_web_search" not in policy
    assert "web_fetch" not in policy
    assert "invoke_agent" not in policy


def test_gemini_policy_can_explicitly_enable_network_and_subagents(tmp_path) -> None:
    adapter = GeminiAdapter(executable=Path("/usr/bin/gemini"), model="flash")
    req = request(tmp_path).model_copy(
        update={
            "permissions": WorkerPermissions(
                network_allowed=True,
                subagents_allowed=True,
            )
        }
    )
    policy = adapter._policy_content(req)

    assert 'toolName = ["google_web_search", "web_fetch"]' in policy
    assert 'toolName = "invoke_agent"' in policy


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
    result = await adapter.execute(worker, request(tmp_path))
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.summary == "ok"
    assert result.structured_output == {"a": 1}
    assert result.usage == {"model": {"tokens": 10}}
