import json

from orchestrator.verification.checks import infer_repository_checks


def test_infers_python_pytest_with_uv(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest>=8"]\n')
    (tmp_path / "uv.lock").write_text("")
    checks = infer_repository_checks(tmp_path, final=False)
    assert [check.command for check in checks] == [["uv", "run", "pytest", "-q"]]


def test_infers_node_test_lint_typecheck_from_lockfile(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "x", "lint": "x", "typecheck": "x"}})
    )
    (tmp_path / "pnpm-lock.yaml").write_text("")
    checks = infer_repository_checks(tmp_path, final=True)
    assert [check.command for check in checks] == [
        ["pnpm", "test"],
        ["pnpm", "lint"],
        ["pnpm", "typecheck"],
    ]


def test_does_not_invent_unknown_commands(tmp_path):
    assert infer_repository_checks(tmp_path, final=True) == []
