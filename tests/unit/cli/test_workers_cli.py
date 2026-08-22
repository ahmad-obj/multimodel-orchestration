from typer.testing import CliRunner

from orchestrator.cli.app import app


def test_workers_command_renders_harness_names() -> None:
    result = CliRunner().invoke(app, ["workers"])
    assert result.exit_code == 0
    assert "Codex" in result.stdout
    assert "Gemini" in result.stdout
    assert "OpenCode" in result.stdout
