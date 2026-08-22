import subprocess

import pytest

from orchestrator.analysis.errors import RepositoryValidationError
from orchestrator.analysis.repository import summarize_repository


def test_repository_summary_is_bounded_and_detects_manifest(tmp_path) -> None:
    subprocess.run(["git","init","-q"],cwd=tmp_path,check=True)
    subprocess.run(["git","config","user.email","x@y.z"],cwd=tmp_path,check=True)
    subprocess.run(["git","config","user.name","x"],cwd=tmp_path,check=True)
    (tmp_path/"pyproject.toml").write_text("[project]\nname='x'\nversion='0.1'\n")
    (tmp_path/"src").mkdir(); (tmp_path/"src"/"a.py").write_text("print('x')\n")
    subprocess.run(["git","add","."],cwd=tmp_path,check=True)
    subprocess.run(["git","commit","-qm","init"],cwd=tmp_path,check=True)
    s=summarize_repository(tmp_path)
    assert "pyproject.toml" in s.manifests
    assert "python" in s.language_hints
    assert len(s.top_level_entries) <= 100


def test_repository_summary_rejects_non_git(tmp_path) -> None:
    with pytest.raises(RepositoryValidationError): summarize_repository(tmp_path)
