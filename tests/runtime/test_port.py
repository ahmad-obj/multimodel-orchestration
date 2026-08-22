from orchestrator.runtime.base import RuntimePort


def test_runtime_port_accepts_matching_runtime_shape() -> None:
    class Runtime:
        async def run(self, job_id: str) -> None:
            pass

        async def resume(self, job_id: str) -> None:
            pass

        async def cancel(self, job_id: str) -> None:
            pass

    assert isinstance(Runtime(), RuntimePort)
