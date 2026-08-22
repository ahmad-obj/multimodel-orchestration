import subprocess
from pathlib import Path

from pydantic import BaseModel

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


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RepositoryValidationError(proc.stderr.strip() or "invalid git repository")
    return proc.stdout.strip()


def summarize_repository(repo_path: Path) -> RepositorySummary:
    repo = repo_path.resolve()
    if not repo.is_dir() or not (repo / ".git").exists():
        try:
            _git(repo, "rev-parse", "--git-dir")
        except Exception as exc:
            raise RepositoryValidationError("path is not a Git repository") from exc
    branch = _git(repo, "branch", "--show-current") or "DETACHED"
    head = _git(repo, "rev-parse", "HEAD")
    dirty = bool(_git(repo, "status", "--porcelain"))
    entries = sorted(p.name for p in repo.iterdir() if p.name != ".git")[:100]
    known = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "requirements.txt", "pnpm-lock.yaml", "uv.lock"}
    manifests = sorted(name for name in entries if name in known)
    suffixes: set[str] = set()
    test_hints: set[str] = set()
    count = 0
    for path in repo.rglob("*"):
        if count >= 400:
            break
        if not path.is_file() or ".git" in path.parts:
            continue
        count += 1
        if path.suffix:
            suffixes.add(path.suffix.lower())
        lower = str(path.relative_to(repo)).lower()
        if "test" in lower or "spec" in lower:
            test_hints.add(str(path.relative_to(repo)))
    lang_map = {".py":"python", ".ts":"typescript", ".tsx":"typescript", ".js":"javascript", ".rs":"rust", ".go":"go", ".cpp":"cpp", ".cc":"cpp"}
    languages = sorted({lang_map[s] for s in suffixes if s in lang_map})
    return RepositorySummary(root=repo, branch=branch, head_sha=head, dirty=dirty, top_level_entries=entries, manifests=manifests, language_hints=languages, test_hints=sorted(test_hints)[:50])
