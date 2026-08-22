from __future__ import annotations

import json
import tomllib
from pathlib import Path

from orchestrator.verification.models import VerificationCheck


def _node_package_manager(repo: Path) -> str | None:
    for filename, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("package-lock.json", "npm"),
        ("bun.lock", "bun"),
        ("bun.lockb", "bun"),
    ):
        if (repo / filename).exists():
            return manager
    return None


def _node_command(manager: str, script: str) -> list[str]:
    if manager == "npm":
        return ["npm", "test"] if script == "test" else ["npm", "run", script]
    if manager in {"pnpm", "yarn"}:
        return [manager, script]
    return ["bun", "run", script]


def infer_repository_checks(repo: Path, *, final: bool) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        if "pytest" in str(data).lower():
            command = (
                ["uv", "run", "pytest", "-q"]
                if (repo / "uv.lock").exists()
                else ["python", "-m", "pytest", "-q"]
            )
            checks.append(VerificationCheck(kind="command", command=command))

    package = repo / "package.json"
    if package.exists():
        try:
            scripts = json.loads(package.read_text()).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        manager = _node_package_manager(repo)
        if manager and "test" in scripts:
            checks.append(
                VerificationCheck(kind="command", command=_node_command(manager, "test"))
            )
        if final and manager:
            for name in ("lint", "typecheck"):
                if name in scripts:
                    checks.append(
                        VerificationCheck(
                            kind="command", command=_node_command(manager, name)
                        )
                    )
    return checks
