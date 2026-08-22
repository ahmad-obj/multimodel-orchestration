import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool


class ProcessRunner:
    def __init__(self) -> None:
        self._running: dict[str, asyncio.subprocess.Process] = {}

    async def run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
        execution_id: str | None = None,
    ) -> ProcessOutcome:
        started = time.perf_counter()
        process_env = os.environ.copy()
        process_env.update(env or {})
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if execution_id is not None:
            self._running[execution_id] = process
        timed_out = False
        try:
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds
                )
            except TimeoutError:
                timed_out = True
                process.kill()
                stdout_b, stderr_b = await process.communicate()
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                raise
        finally:
            if execution_id is not None:
                self._running.pop(execution_id, None)

        return ProcessOutcome(
            returncode=process.returncode,
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
            duration_seconds=time.perf_counter() - started,
            timed_out=timed_out,
        )

    async def cancel(self, execution_id: str) -> bool:
        process = self._running.get(execution_id)
        if process is None or process.returncode is not None:
            return False
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            process.kill()
            await process.wait()
        return True
