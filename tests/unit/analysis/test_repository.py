import subprocess

import pytest

from orchestrator.analysis.errors import RepositoryValidationError
from orchestrator.analysis.repository import summarize_repository


def _git(repo, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _init(repo) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# fixture\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")


def test_python_repo_detects_manifest_language_and_test_command(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "pyproject.toml").write_text('[project]\nname="fixture"\n[tool.pytest.ini_options]\n')
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x(): assert True\n")

    summary = summarize_repository(repo)

    assert "pyproject.toml" in summary.manifests
    assert "python" in summary.language_hints
    assert any(
        command in summary.test_commands for command in ["uv run pytest -q", "python -m pytest -q"]
    )
    assert any("test_x.py" in item for item in summary.test_hints)


def test_node_repo_detects_package_test_command(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "package.json").write_text('{"scripts":{"test":"vitest run"}}')
    (repo / "src").mkdir()
    (repo / "src" / "x.ts").write_text("export const x = 1\n")

    summary = summarize_repository(repo)

    assert "package.json" in summary.manifests
    assert "typescript" in summary.language_hints
    assert "npm test" in summary.test_commands


def test_repository_summary_is_bounded(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    for index in range(450):
        (repo / f"f{index}.py").write_text("x = 1\n")

    summary = summarize_repository(repo)

    assert len(summary.top_level_entries) <= 100


def test_repository_summary_rejects_non_git(tmp_path) -> None:
    with pytest.raises(RepositoryValidationError):
        summarize_repository(tmp_path)
