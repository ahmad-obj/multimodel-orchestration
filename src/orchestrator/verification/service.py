from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Protocol

from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.domain.results import WorkerResult
from orchestrator.domain.tasks import SubtaskSpec
from orchestrator.verification.checks import infer_repository_checks
from orchestrator.verification.models import (
    CheckResult,
    ReviewDecision,
    VerificationCheck,
    VerificationResult,
)
from orchestrator.workers.process import ProcessRunner


class ReviewProvider(Protocol):
    async def review(
        self,
        *,
        kind: str,
        context: dict[str, object],
        implementer_worker_id: str,
    ) -> ReviewDecision | None: ...


class VerificationService:
    def __init__(
        self,
        artifact_store,
        *,
        process_runner=None,
        review_provider: ReviewProvider | None = None,
        verification_repository=None,
        event_bus=None,
    ) -> None:
        self.artifact_store = artifact_store
        self.process_runner = process_runner or ProcessRunner()
        self.review_provider = review_provider
        self.verification_repository = verification_repository
        self.event_bus = event_bus

    async def _publish(self, event: OrchestratorEvent) -> None:
        if self.event_bus is not None:
            await self.event_bus.publish(event)

    async def _run_command_check(
        self,
        job_id: str,
        task_id: str,
        index: int,
        check: VerificationCheck,
        workspace: Path,
    ) -> tuple[CheckResult, list]:
        outcome = await self.process_runner.run(
            check.command or [], cwd=workspace, timeout_seconds=900
        )
        passed = not outcome.timed_out and outcome.returncode == 0
        artifact = None
        artifacts = []
        if outcome.stdout or outcome.stderr or not passed:
            artifact = self.artifact_store.write_text(
                job_id,
                task_id,
                f"verification-{index}.log",
                (
                    f'$ {" ".join(check.command or [])}\n\n'
                    f"STDOUT:\n{outcome.stdout}\nSTDERR:\n{outcome.stderr}"
                ),
            )
            artifacts.append(artifact)
        summary = (
            "command passed"
            if passed
            else "command timed out"
            if outcome.timed_out
            else f"command exited {outcome.returncode}"
        )
        return (
            CheckResult(
                kind=check.kind,
                passed=passed,
                summary=summary,
                artifact=artifact,
            ),
            artifacts,
        )

    async def verify(
        self,
        job_id: str,
        subtask: SubtaskSpec,
        worker_result: WorkerResult,
        workspace: Path,
        checks: list[VerificationCheck],
    ) -> VerificationResult:
        await self._publish(
            OrchestratorEvent(
                type=EventType.VERIFICATION_STARTED,
                job_id=job_id,
                task_id=subtask.id,
                worker_id=worker_result.worker_id,
            )
        )
        results: list[CheckResult] = []
        artifacts = []
        required_fail = False
        for index, check in enumerate(checks):
            if check.kind == "command":
                check_result, command_artifacts = await self._run_command_check(
                    job_id, subtask.id, index, check, workspace
                )
                artifacts.extend(command_artifacts)
            elif check.kind == "changed_files":
                missing = []
                for name in worker_result.changed_files:
                    relative = PurePosixPath(name)
                    candidate = workspace / Path(*relative.parts)
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or not candidate.exists()
                    ):
                        missing.append(name)
                passed = not missing
                check_result = CheckResult(
                    kind=check.kind,
                    passed=passed,
                    summary=(
                        "claimed changed files exist"
                        if passed
                        else f'missing claimed changed files: {", ".join(missing)}'
                    ),
                )
            else:
                decision = (
                    None
                    if self.review_provider is None
                    else await self.review_provider.review(
                        kind=check.kind,
                        context={
                            "objective": subtask.objective,
                            "constraints": subtask.context_requirements,
                            "worker_summary": worker_result.summary,
                            "changed_files": worker_result.changed_files,
                            "artifacts": [item.uri for item in worker_result.artifacts],
                        },
                        implementer_worker_id=worker_result.worker_id,
                    )
                )
                if decision is None:
                    passed = not check.required
                    summary = f"{check.kind} unavailable"
                else:
                    passed = decision.accepted
                    summary = (
                        "review accepted"
                        if passed
                        else "review rejected: " + "; ".join(decision.reasons)
                    )
                check_result = CheckResult(
                    kind=check.kind,
                    passed=passed,
                    summary=summary,
                )
            results.append(check_result)
            if check.required and not check_result.passed:
                required_fail = True

        verified = VerificationResult(
            passed=not required_fail,
            checks=results,
            summary="verification passed" if not required_fail else "verification failed",
            artifacts=artifacts,
        )
        if self.verification_repository is not None:
            await self.verification_repository.record(
                job_id, subtask.id, verified.model_dump_json()
            )
        await self._publish(
            OrchestratorEvent(
                type=(
                    EventType.VERIFICATION_PASSED
                    if verified.passed
                    else EventType.VERIFICATION_FAILED
                ),
                job_id=job_id,
                task_id=subtask.id,
                worker_id=worker_result.worker_id,
                payload={"summary": verified.summary},
            )
        )
        return verified

    async def verify_repository(self, job_id: str, workspace: Path) -> VerificationResult:
        checks = infer_repository_checks(workspace, final=True)
        await self._publish(
            OrchestratorEvent(
                type=EventType.VERIFICATION_STARTED,
                job_id=job_id,
                task_id="__final__",
            )
        )
        results: list[CheckResult] = []
        artifacts = []
        failed = False
        for index, check in enumerate(checks):
            if check.kind != "command":
                continue
            check_result, command_artifacts = await self._run_command_check(
                job_id, "__final__", index, check, workspace
            )
            results.append(check_result)
            artifacts.extend(command_artifacts)
            if check.required and not check_result.passed:
                failed = True

        verified = VerificationResult(
            passed=not failed,
            checks=results,
            summary="verification passed" if not failed else "verification failed",
            artifacts=artifacts,
        )
        if self.verification_repository is not None:
            await self.verification_repository.record(
                job_id, "__final__", verified.model_dump_json()
            )
        await self._publish(
            OrchestratorEvent(
                type=(
                    EventType.VERIFICATION_PASSED
                    if verified.passed
                    else EventType.VERIFICATION_FAILED
                ),
                job_id=job_id,
                task_id="__final__",
                payload={"summary": verified.summary},
            )
        )
        return verified
