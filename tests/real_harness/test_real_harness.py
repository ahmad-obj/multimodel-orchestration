import os
from pathlib import Path

import pytest

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.workers import (
    WorkerDescriptor,
    WorkerPermissions,
    WorkerProfile,
    WorkerRequest,
)
from orchestrator.workers.codex import CodexAdapter
from orchestrator.workers.gemini import GeminiAdapter
from orchestrator.workers.opencode import OpenCodeAdapter
from orchestrator.workspace.git import GitClient

pytestmark = pytest.mark.real_harness

if os.environ.get("ORCHESTRATOR_REAL_HARNESS_TESTS") != "1":
    pytest.skip(
        "set ORCHESTRATOR_REAL_HARNESS_TESTS=1 to invoke installed AI harnesses",
        allow_module_level=True,
    )


_SMOKE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "structured_output": {
            "type": "object",
            "properties": {"marker": {"type": "string"}},
            "required": ["marker"],
            "additionalProperties": False,
        },
        "confidence": {"type": "number"},
    },
    "required": ["summary", "structured_output", "confidence"],
    "additionalProperties": False,
}


def _cases():
    return [
        ("codex", CodexAdapter(), os.environ.get("ORCHESTRATOR_CODEX_MODEL", "default")),
        ("gemini", GeminiAdapter(), os.environ.get("ORCHESTRATOR_GEMINI_MODEL", "auto")),
        (
            "opencode",
            OpenCodeAdapter(),
            os.environ.get("ORCHESTRATOR_OPENCODE_MODEL", "opencode/mimo-v2.5-free"),
        ),
    ]


def _profile(harness: str, model: str) -> WorkerProfile:
    return WorkerProfile(
        id=f"{harness}/real-smoke",
        harness=harness,
        model=model,
        capabilities={"simple_tasks": 1.0, "reasoning": 1.0},
        reliability=1.0,
        speed=1.0,
        cost_class=CostClass.INCLUDED if harness == "codex" else CostClass.FREE,
        parallel_capacity=1,
        tools={"filesystem"},
        can_manage=False,
        can_modify_repo=False,
        is_paid=False,
    )


@pytest.mark.parametrize(("harness", "adapter", "model"), _cases())
async def test_real_harness_read_only_smoke(tmp_path: Path, harness, adapter, model) -> None:
    (tmp_path / "README.md").write_text("REAL_HARNESS_SMOKE\n")
    git = GitClient()
    await git._run(["git", "init"], tmp_path)
    before = await git.status_porcelain(tmp_path)

    discovered = await adapter.discover()
    if not discovered or discovered[0].status is not WorkerStatus.AVAILABLE:
        pytest.skip(f"{harness} executable/policy interface is unavailable")
    worker = WorkerDescriptor(
        profile=_profile(harness, model),
        executable_path=discovered[0].executable_path,
        status=WorkerStatus.AVAILABLE,
        health_reason=None,
    )
    request = WorkerRequest(
        job_id=f"real-smoke-{harness}",
        task_id="read-only-smoke",
        objective=(
            "Read README.md and return only JSON matching the supplied schema: "
            '{"summary":"SMOKE_OK","structured_output":{"marker":"SMOKE_OK"},'
            '"confidence":1.0}. Do not modify files, use network access, or delegate to subagents.'
        ),
        repo_path=tmp_path,
        workspace_path=None,
        read_only=True,
        permissions=WorkerPermissions(network_allowed=False, subagents_allowed=False),
        expected_output_schema=_SMOKE_SCHEMA,
        timeout_seconds=180,
    )

    result = await adapter.execute(worker, request)

    assert result.status is ExecutionStatus.SUCCEEDED, result.errors
    assert result.structured_output.get("marker") == "SMOKE_OK"
    assert await git.status_porcelain(tmp_path) == before
