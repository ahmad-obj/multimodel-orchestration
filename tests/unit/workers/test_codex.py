from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile, WorkerRequest
from orchestrator.workers.codex import CodexAdapter


def profile() -> WorkerProfile:
    return WorkerProfile(
        id="codex/default",
        harness="codex",
        model="default",
        capabilities={"coding": 0.95},
        reliability=0.9,
        speed=0.6,
        cost_class=CostClass.INCLUDED,
        parallel_capacity=1,
        tools={"filesystem", "shell", "git"},
        can_manage=True,
        can_modify_repo=True,
        is_paid=False,
    )


def test_codex_command_uses_structured_exec(tmp_path) -> None:
    adapter = CodexAdapter(executable=Path("/usr/bin/codex"))
    cmd = adapter.build_command(
        tmp_path,
        "inspect",
        tmp_path / "schema.json",
        tmp_path / "final.json",
        read_only=True,
    )
    assert cmd[:2] == ["/usr/bin/codex", "exec"]
    assert "--json" in cmd
    assert "--output-schema" in cmd
    assert "--output-last-message" in cmd
    assert "read-only" in cmd
    assert "features.multi_agent=false" in cmd
    assert "features.multi_agent_v2=false" in cmd


async def test_codex_execute_normalizes_fake_result(tmp_path) -> None:
    fake = tmp_path / "codex"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys,pathlib\n"
        "p=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
        "p.write_text(json.dumps({'summary':'ok','confidence':0.8,'structured_output':{'x':1}}))\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':2}}))\n"
    )
    fake.chmod(0o755)
    adapter = CodexAdapter(executable=fake)
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
    assert result.structured_output == {"x": 1}
    assert result.confidence == 0.8
