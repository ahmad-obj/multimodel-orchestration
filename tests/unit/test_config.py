from orchestrator.config import AppPaths


def test_app_paths_respect_xdg(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    paths = AppPaths.from_environment()
    assert paths.config_dir == tmp_path / "cfg" / "multimodal-orchestration"
    assert paths.data_dir == tmp_path / "data" / "multimodal-orchestration"
    assert paths.database == paths.data_dir / "orchestrator.db"
