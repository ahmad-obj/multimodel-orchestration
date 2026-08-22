import json
import shutil
import uuid
from pathlib import Path

from orchestrator.domain.common import CostClass, ExecutionStatus, WorkerStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.workers import WorkerDescriptor, WorkerProfile, WorkerRequest
from orchestrator.workers.base import WorkerAdapter
from orchestrator.workers.process import ProcessRunner


class OpenCodeAdapter(WorkerAdapter):
    harness = "opencode"

    def __init__(
        self,
        executable: Path | None = None,
        model: str = "auto",
        runner: ProcessRunner | None = None,
    ) -> None:
        self.executable = executable or (
            Path(found) if (found := shutil.which("opencode")) else None
        )
        self.model = model
        self.runner = runner or ProcessRunner()

    def build_command(self, workspace: Path, prompt: str, *, model: str | None = None) -> list[str]:
        if self.executable is None:
            raise RuntimeError("opencode executable unavailable")
        return [
            str(self.executable),
            "run",
            prompt,
            "--model",
            model or self.model,
            "--format",
            "json",
            "--dir",
            str(workspace),
        ]

    async def discover(self) -> list[WorkerDescriptor]:
        if self.executable is None:
            return []
        profile = WorkerProfile(
            id=f"opencode/{self.model}",
            harness="opencode",
            model=self.model,
            capabilities={},
            reliability=0.5,
            speed=0.6,
            cost_class=CostClass.FREE,
            parallel_capacity=1,
            tools={"filesystem", "shell", "git"},
            can_manage=True,
            can_modify_repo=True,
            is_paid=False,
        )
        descriptor = WorkerDescriptor(
            profile=profile,
            executable_path=self.executable,
            status=WorkerStatus.AVAILABLE,
        )
        return [await self.health_check(descriptor)]

    async def health_check(self, worker: WorkerDescriptor) -> WorkerDescriptor:
        if worker.executable_path is None or not worker.executable_path.exists():
            return worker.model_copy(
                update={
                    "status": WorkerStatus.UNAVAILABLE,
                    "health_reason": "missing executable",
                }
            )
        outcome = await self.runner.run(
            [str(worker.executable_path), "run", "--help"],
            cwd=Path.cwd(),
            timeout_seconds=10,
        )
        text = outcome.stdout + outcome.stderr
        required = ["--format", "--model", "--dir"]
        if outcome.returncode != 0 or any(flag not in text for flag in required):
            return worker.model_copy(
                update={
                    "status": WorkerStatus.UNAVAILABLE,
                    "health_reason": "required run flags unsupported",
                }
            )
        return worker.model_copy(update={"status": WorkerStatus.AVAILABLE, "health_reason": None})

    def _config_content(self, request: WorkerRequest) -> str:
        permission = {
            "edit": "deny" if request.read_only else "allow",
            "bash": {
                "*": "deny",
                "git status*": "allow",
                "git diff*": "allow",
                "git log*": "allow",
                "git push*": "deny",
                "sudo *": "deny",
                "rm -rf /*": "deny",
            },
            "task": "allow" if request.permissions.subagents_allowed else "deny",
            "webfetch": "allow" if request.permissions.network_allowed else "deny",
        }
        for prefix in request.permissions.allowed_shell_prefixes:
            permission["bash"][f"{prefix}*"] = "allow"
        return json.dumps({"permission": permission})

    async def execute(self, worker: WorkerDescriptor, request: WorkerRequest) -> WorkerResult:
        execution_id = request.execution_id or str(uuid.uuid4())
        workspace = request.workspace_path or request.repo_path
        cmd = self.build_command(workspace, request.objective, model=worker.profile.model)
        env = {"OPENCODE_CONFIG_CONTENT": self._config_content(request)}
        outcome = await self.runner.run(
            cmd,
            cwd=workspace,
            timeout_seconds=request.timeout_seconds,
            env=env,
            execution_id=execution_id,
        )
        if outcome.timed_out:
            return WorkerResult(
                execution_id=execution_id,
                worker_id=worker.profile.id,
                task_id=request.task_id,
                status=ExecutionStatus.TIMED_OUT,
                summary="OpenCode timed out",
                errors=[outcome.stderr],
                duration_seconds=outcome.duration_seconds,
            )
        if outcome.returncode != 0:
            return WorkerResult(
                execution_id=execution_id,
                worker_id=worker.profile.id,
                task_id=request.task_id,
                status=ExecutionStatus.FAILED,
                summary="OpenCode failed",
                errors=[outcome.stderr],
                duration_seconds=outcome.duration_seconds,
            )
        final_text = ""
        unknown: list[dict[str, object]] = []
        for line in outcome.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type") if isinstance(event, dict) else None
            if event_type in {"message", "result"}:
                content = event.get("content") or event.get("text") or event.get("response")
                if isinstance(content, str):
                    final_text = content
            elif isinstance(event, dict):
                unknown.append(event)
        try:
            parsed = (
                json.loads(final_text)
                if request.expected_output_schema is not None
                else {"summary": final_text}
            )
        except Exception as exc:
            return WorkerResult(
                execution_id=execution_id,
                worker_id=worker.profile.id,
                task_id=request.task_id,
                status=ExecutionStatus.FAILED,
                summary="OpenCode returned invalid structured output",
                errors=[str(exc)],
                duration_seconds=outcome.duration_seconds,
                usage={"unknown_events": unknown},
            )
        return WorkerResult(
            execution_id=execution_id,
            worker_id=worker.profile.id,
            task_id=request.task_id,
            status=ExecutionStatus.SUCCEEDED,
            summary=str(parsed.get("summary", "")),
            structured_output=dict(parsed.get("structured_output", {})),
            confidence=float(parsed.get("confidence", 0.0)),
            usage={"unknown_events": unknown},
            duration_seconds=outcome.duration_seconds,
        )

    async def cancel(self, execution_id: str) -> None:
        await self.runner.cancel(execution_id)
