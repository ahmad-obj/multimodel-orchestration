import json
import shutil
import tempfile
import uuid
from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile, WorkerRequest
from orchestrator.workers.base import WorkerAdapter
from orchestrator.workers.process import ProcessRunner


class CodexAdapter(WorkerAdapter):
    harness = "codex"

    def __init__(self, executable: Path | None = None, runner: ProcessRunner | None = None) -> None:
        self.executable = executable or (Path(found) if (found := shutil.which("codex")) else None)
        self.runner = runner or ProcessRunner()

    def build_command(
        self,
        workspace: Path,
        prompt: str,
        schema_path: Path,
        final_path: Path,
        *,
        read_only: bool,
    ) -> list[str]:
        if self.executable is None:
            raise RuntimeError("codex executable unavailable")
        sandbox = "read-only" if read_only else "workspace-write"
        return [
            str(self.executable),
            "exec",
            "--ephemeral",
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(final_path),
            "--sandbox",
            sandbox,
            "--ignore-rules",
            "-c",
            "features.multi_agent=false",
            "-c",
            "features.multi_agent_v2=false",
            "-c",
            'web_search="disabled"',
            "-c",
            "sandbox_workspace_write.network_access=false",
            "-C",
            str(workspace),
            prompt,
        ]

    async def discover(self) -> list[WorkerDescriptor]:
        if self.executable is None:
            return []
        profile = WorkerProfile(
            id="codex/default",
            harness="codex",
            model="default",
            capabilities={},
            reliability=0.5,
            speed=0.5,
            cost_class=CostClass.INCLUDED,
            parallel_capacity=1,
            tools={"filesystem", "shell", "git"},
            can_manage=True,
            can_modify_repo=True,
            is_paid=False,
        )
        descriptor = WorkerDescriptor(
            profile=profile, executable_path=self.executable, status=WorkerStatus.AVAILABLE
        )
        return [await self.health_check(descriptor)]

    async def health_check(self, worker: WorkerDescriptor) -> WorkerDescriptor:
        if worker.executable_path is None or not worker.executable_path.exists():
            return worker.model_copy(update={"status": WorkerStatus.UNAVAILABLE, "health_reason": "missing executable"})
        outcome = await self.runner.run(
            [str(worker.executable_path), "exec", "--help"],
            cwd=Path.cwd(),
            timeout_seconds=10,
        )
        required = ["--json", "--output-schema", "--output-last-message", "--sandbox"]
        text = outcome.stdout + outcome.stderr
        if outcome.returncode != 0 or any(flag not in text for flag in required):
            return worker.model_copy(update={"status": WorkerStatus.UNAVAILABLE, "health_reason": "required exec isolation flags unsupported"})
        return worker.model_copy(update={"status": WorkerStatus.AVAILABLE, "health_reason": None})

    async def execute(self, worker: WorkerDescriptor, request: WorkerRequest) -> WorkerResult:
        execution_id = str(uuid.uuid4())
        workspace = request.workspace_path or request.repo_path
        with tempfile.TemporaryDirectory(prefix="orchestrator-codex-") as tmp:
            tmp_path = Path(tmp)
            schema_path = tmp_path / "schema.json"
            final_path = tmp_path / "final.json"
            schema_path.write_text(json.dumps(request.expected_output_schema or {"type": "object"}))
            cmd = self.build_command(
                workspace,
                request.objective,
                schema_path,
                final_path,
                read_only=request.read_only,
            )
            outcome = await self.runner.run(
                cmd,
                cwd=workspace,
                timeout_seconds=request.timeout_seconds,
                execution_id=execution_id,
            )
            if outcome.timed_out:
                return WorkerResult(
                    execution_id=execution_id, worker_id=worker.profile.id, task_id=request.task_id,
                    status=ExecutionStatus.TIMED_OUT, summary="Codex timed out",
                    duration_seconds=outcome.duration_seconds, errors=[outcome.stderr],
                )
            if outcome.returncode != 0:
                return WorkerResult(
                    execution_id=execution_id, worker_id=worker.profile.id, task_id=request.task_id,
                    status=ExecutionStatus.FAILED, summary="Codex failed",
                    duration_seconds=outcome.duration_seconds, errors=[outcome.stderr],
                )
            try:
                payload = json.loads(final_path.read_text())
            except Exception as exc:
                return WorkerResult(
                    execution_id=execution_id, worker_id=worker.profile.id, task_id=request.task_id,
                    status=ExecutionStatus.FAILED, summary="Codex returned invalid structured output",
                    duration_seconds=outcome.duration_seconds, errors=[str(exc)],
                )
            usage: dict[str, object] = {}
            for line in outcome.stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and isinstance(event.get("usage"), dict):
                    usage.update(event["usage"])
            return WorkerResult(
                execution_id=execution_id,
                worker_id=worker.profile.id,
                task_id=request.task_id,
                status=ExecutionStatus.SUCCEEDED,
                summary=str(payload.get("summary", "")),
                structured_output=dict(payload.get("structured_output", {})),
                confidence=float(payload.get("confidence", 0.0)),
                usage=usage,
                duration_seconds=outcome.duration_seconds,
            )

    async def cancel(self, execution_id: str) -> None:
        await self.runner.cancel(execution_id)
