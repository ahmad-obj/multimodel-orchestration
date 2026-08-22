import ast
from pathlib import Path

SOURCE_ROOT = Path("src/orchestrator")
RUNTIME_PATH = SOURCE_ROOT / "runtime"

IGNORED_DIRS = {"__pycache__", ".git", ".mypy_cache"}


def _is_langgraph_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.startswith("langgraph") for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        if node.module is None:
            return False
        return node.module.startswith("langgraph")
    return False


def test_no_langgraph_imports_outside_runtime() -> None:
    violations: list[tuple[str, int, str]] = []
    for py_file in sorted(SOURCE_ROOT.rglob("*.py")):
        if any(part in IGNORED_DIRS for part in py_file.parts):
            continue
        try:
            rel = py_file.relative_to(SOURCE_ROOT)
        except ValueError:
            continue
        is_runtime_file = rel.parts[0] == "runtime" if rel.parts else False
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        for node in ast.walk(tree):
            if not _is_langgraph_import(node):
                continue
            if is_runtime_file:
                continue
            violations.append(
                (str(rel), node.lineno, ast.get_source_segment(py_file.read_text(), node) or "")
            )
    assert not violations, (
        "LangGraph imports found outside src/orchestrator/runtime/:\n"
        + "\n".join(f"  {path}:{lineno}: {segment}" for path, lineno, segment in violations)
    )
