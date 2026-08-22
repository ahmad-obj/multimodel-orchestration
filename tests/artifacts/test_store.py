import pytest

from orchestrator.artifacts.store import ArtifactStore


def test_artifact_store_round_trips_text(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = store.write_text("job-1", "task-2", "test-output.txt", "PASS\n")
    assert ref.uri == "artifact://job-1/task-2/test-output.txt"
    assert store.read_text(ref) == "PASS\n"


def test_artifact_store_rejects_path_traversal(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="artifact filename"):
        store.write_text("job-1", "task-2", "../escape.txt", "bad")
