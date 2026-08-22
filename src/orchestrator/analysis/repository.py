import json
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from orchestrator.analysis.errors import RepositoryValidationError


class RepositorySummary(BaseModel):
    root: Path
    branch: str
    head_sha: str
    dirty: bool
    top_level_entries: list[str]
    manifests: list[str]
    language_hints: list[str]
    test_hints: list[str]
    test_commands: list[str] = Field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepositoryValidationError("unable to inspect Git repository") from exc
    if proc.returncode != 0:
        raise RepositoryValidationError(proc.stderr.strip() or "invalid Git repository")
    return proc.stdout.strip()


def _test_commands(repo: Path, manifests: set[str]) -> list[str]:
    commands: list[str] = []
    if "pyproject.toml" in manifests or "pytest.ini" in manifests or "tox.ini" in manifests:
        commands.append(
            "uv run pytest -q" if (repo / "uv.lock").exists() else "python -m pytest -q"
        )
    elif "requirements.txt" in manifests and (repo / "tests").exists():
        commands.append("python -m pytest -q")

    package_json = repo / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload.get("scripts"), dict) and "test" in payload["scripts"]:
            if (repo / "pnpm-lock.yaml").exists():
                commands.append("pnpm test")
            elif (repo / "yarn.lock").exists():
                commands.append("yarn test")
            else:
                commands.append("npm test")
    if "Cargo.toml" in manifests:
        commands.append("cargo test")
    if "go.mod" in manifests:
        commands.append("go test ./...")
    return commands[:8]


def summarize_repository(repo_path: Path) -> RepositorySummary:
    repo = repo_path.expanduser().resolve()
    if not repo.is_dir():
        raise RepositoryValidationError("repository path does not exist or is not a directory")
    try:
        _git(repo, "rev-parse", "--git-dir")
    except RepositoryValidationError as exc:
        raise RepositoryValidationError("path is not a Git repository") from exc

    branch = _git(repo, "branch", "--show-current") or "DETACHED"
    head = _git(repo, "rev-parse", "HEAD")
    dirty = bool(_git(repo, "status", "--porcelain"))
    entries = sorted(path.name for path in repo.iterdir() if path.name != ".git")[:100]
    known = {
        "pyproject.toml",
        "pytest.ini",
        "tox.ini",
        "requirements.txt",
        "uv.lock",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
        "Cargo.toml",
        "go.mod",
    }
    manifests = sorted(name for name in entries if name in known)

    suffixes: set[str] = set()
    test_hints: set[str] = set()
    scanned = 0
    skip_dirs = {".git", ".venv", "venv", "node_modules", "dist", "build", "target"}
    for path in repo.rglob("*"):
        if scanned >= 400:
            break
        rel = path.relative_to(repo)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if not path.is_file():
            continue
        scanned += 1
        if path.suffix:
            suffixes.add(path.suffix.lower())
        lower = str(rel).lower()
        if "test" in lower or "spec" in lower:
            test_hints.add(str(rel))

    language_map = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".cpp": "cpp",
        ".cc": "cpp",
    }
    languages = sorted({language_map[suffix] for suffix in suffixes if suffix in language_map})
    return RepositorySummary(
        root=repo,
        branch=branch,
        head_sha=head,
        dirty=dirty,
        top_level_entries=entries,
        manifests=manifests,
        language_hints=languages,
        test_hints=sorted(test_hints)[:50],
        test_commands=_test_commands(repo, set(manifests)),
    )
