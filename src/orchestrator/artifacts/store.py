from pathlib import Path, PurePosixPath

from orchestrator.domain.artifacts import ArtifactRef


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, job_id: str, task_id: str, filename: str) -> Path:
        relative = PurePosixPath(filename)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("artifact filename must stay inside its task directory")
        return self.root / "artifacts" / job_id / task_id / Path(*relative.parts)

    def _resolve(self, ref: ArtifactRef) -> Path:
        prefix = "artifact://"
        if not ref.uri.startswith(prefix):
            raise ValueError("invalid artifact URI")
        relative = PurePosixPath(ref.uri[len(prefix):])
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 3:
            raise ValueError("invalid artifact URI")
        path = self.root / "artifacts" / Path(*relative.parts)
        root = (self.root / "artifacts").resolve()
        resolved = path.resolve()
        if root not in resolved.parents:
            raise ValueError("artifact URI escapes store")
        return resolved

    def write_text(self, job_id: str, task_id: str, filename: str, value: str) -> ArtifactRef:
        path = self._path(job_id, task_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return ArtifactRef(uri=f"artifact://{job_id}/{task_id}/{filename}")

    def write_bytes(self, job_id: str, task_id: str, filename: str, value: bytes) -> ArtifactRef:
        path = self._path(job_id, task_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
        return ArtifactRef(uri=f"artifact://{job_id}/{task_id}/{filename}")

    def read_text(self, ref: ArtifactRef) -> str:
        return self._resolve(ref).read_text(encoding="utf-8")

    def read_bytes(self, ref: ArtifactRef) -> bytes:
        return self._resolve(ref).read_bytes()
