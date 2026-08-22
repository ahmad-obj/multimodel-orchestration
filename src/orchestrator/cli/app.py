from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from orchestrator.domain.common import WorkerStatus
from orchestrator.workers.codex import CodexAdapter
from orchestrator.workers.gemini import GeminiAdapter
from orchestrator.workers.opencode import OpenCodeAdapter

app = typer.Typer(help="Vendor-neutral autonomous coding-agent orchestrator.")
console = Console()


@app.callback()
def _root() -> None:
    """Multimodal orchestration CLI."""


def _adapters():
    return [CodexAdapter(), GeminiAdapter(), OpenCodeAdapter()]


@app.command("workers")
def workers() -> None:
    table = Table("Harness", "Worker ID", "Executable", "Status", "Health")
    names = {"codex": "Codex", "gemini": "Gemini", "opencode": "OpenCode"}
    for adapter in _adapters():
        executable = getattr(adapter, "executable", None)
        worker_id = f"{adapter.harness}/default"
        status = WorkerStatus.AVAILABLE if executable else WorkerStatus.UNAVAILABLE
        table.add_row(
            names.get(adapter.harness, adapter.harness),
            worker_id,
            str(executable or "-"),
            status.value,
            "not health-checked" if executable else "not installed",
        )
    console.print(table)


def main() -> None:
    app()
