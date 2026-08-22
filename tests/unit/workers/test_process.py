import asyncio
import sys

from orchestrator.workers.process import ProcessRunner


async def test_process_runner_captures_output(tmp_path) -> None:
    out = await ProcessRunner().run(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        cwd=tmp_path,
        timeout_seconds=5,
    )
    assert out.returncode == 0
    assert out.stdout.strip() == "out"
    assert out.stderr.strip() == "err"
    assert out.timed_out is False


async def test_process_runner_marks_timeout(tmp_path) -> None:
    out = await ProcessRunner().run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        timeout_seconds=1,
    )
    assert out.timed_out is True


async def test_process_runner_can_cancel_registered_process(tmp_path) -> None:
    runner = ProcessRunner()
    task = asyncio.create_task(
        runner.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            timeout_seconds=60,
            execution_id="exec-1",
        )
    )
    await asyncio.sleep(0.1)
    assert await runner.cancel("exec-1") is True
    await task
    assert await runner.cancel("exec-1") is False
