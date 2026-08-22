from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from orchestrator.bootstrap import OrchestratorApplication, build_application

app = typer.Typer(help="Vendor-neutral autonomous coding-agent orchestrator.")
console = Console()


@app.callback()
def _root() -> None:
    """Multimodal orchestration CLI."""


def _value(value: Any) -> str:
    return str(getattr(value, "value", value))


async def _with_application(
    operation: Callable[[OrchestratorApplication], Awaitable[Any]],
):
    application = await build_application()
    try:
        return await operation(application)
    finally:
        await application.close()


def _run(operation: Callable[[OrchestratorApplication], Awaitable[Any]]):
    try:
        return asyncio.run(_with_application(operation))
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def _print_job_result(result) -> None:
    table = Table("Job", "Status", "Manager", "Final SHA", "Question")
    table.add_row(
        result.job_id,
        _value(result.status),
        str(getattr(result, "manager_worker_id", None) or "-"),
        str(getattr(result, "final_sha", None) or "-"),
        str(getattr(result, "human_question", None) or "-"),
    )
    console.print(table)


@app.command("run")
def run_job(
    repo_path: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    objective: str = typer.Argument(...),
    job_id: str | None = typer.Option(None, "--job-id"),
) -> None:
    async def operation(application: OrchestratorApplication):
        return await application.control.run(repo_path, objective, job_id=job_id)

    _print_job_result(_run(operation))


@app.command("jobs")
def jobs(limit: int = typer.Option(50, min=1, max=500)) -> None:
    async def operation(application: OrchestratorApplication):
        return await application.control.list_jobs(limit=limit)

    rows = _run(operation)
    table = Table("Job", "Status", "Manager", "Objective")
    for row in rows:
        table.add_row(
            row.job_id,
            _value(row.status),
            str(row.manager_worker_id or "-"),
            row.original_request,
        )
    console.print(table)


@app.command("job")
def inspect_job(job_id: str) -> None:
    async def operation(application: OrchestratorApplication):
        return await application.control.inspect(job_id)

    snapshot = _run(operation)
    console.print(f"[bold]Job:[/bold] {snapshot.job.job_id}")
    console.print(f"Status: {_value(snapshot.job.status)}")
    console.print(f"Manager: {snapshot.job.manager_worker_id or '-'}")
    console.print(f"Repository: {snapshot.job.repo_path}")
    console.print(f"Objective: {snapshot.job.original_request}")

    table = Table("Task", "Status", "Worker", "Objective")
    for item in snapshot.tasks:
        table.add_row(
            item.spec.id,
            _value(item.status),
            str(item.assigned_worker_id or "-"),
            item.spec.objective,
        )
    console.print(table)
    console.print(
        f"Attempts: {len(snapshot.attempts)}  Artifacts: {len(snapshot.artifacts)}  "
        f"Decisions: {len(snapshot.decisions)}  Verifications: {len(snapshot.verifications)}  "
        f"Events: {len(snapshot.events)}"
    )


@app.command("resume")
def resume_job(job_id: str) -> None:
    async def operation(application: OrchestratorApplication):
        return await application.control.resume(job_id)

    _print_job_result(_run(operation))


@app.command("cancel")
def cancel_job(job_id: str) -> None:
    async def operation(application: OrchestratorApplication):
        return await application.control.cancel(job_id)

    result = _run(operation)
    console.print(f"{result.job_id}: {_value(result.status)}")


@app.command("approve")
def approve_paid(job_id: str, task_id: str, worker_id: str) -> None:
    """Approve one explicitly requested paid-worker escalation."""

    async def operation(application: OrchestratorApplication):
        return await application.control.approve(job_id, task_id, worker_id)

    _print_job_result(_run(operation))


@app.command("reject")
def reject_paid(job_id: str, task_id: str) -> None:
    """Reject a pending paid-worker escalation and stop that job."""

    async def operation(application: OrchestratorApplication):
        return await application.control.reject_approval(job_id, task_id)

    result = _run(operation)
    console.print(f"{result.job_id}: {_value(result.status)}")


@app.command("workers")
def workers() -> None:
    async def operation(application: OrchestratorApplication):
        await application.registry.refresh()
        return application.registry.all()

    rows = _run(operation)
    table = Table("Worker ID", "Harness", "Model", "Cost", "Status", "Executable", "Health")
    for worker in rows:
        table.add_row(
            worker.profile.id,
            worker.profile.harness,
            worker.profile.model,
            _value(worker.profile.cost_class),
            _value(worker.status),
            str(worker.executable_path or "-"),
            str(worker.health_reason or "ok"),
        )
    console.print(table)


def main() -> None:
    app()
