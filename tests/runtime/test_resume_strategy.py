from types import SimpleNamespace

from orchestrator.runtime.langgraph import _resume_starts_new_cycle


def test_resume_starts_new_cycle_when_no_checkpoint_exists():
    snapshot = SimpleNamespace(created_at=None, next=())

    assert _resume_starts_new_cycle(snapshot)


def test_resume_starts_new_cycle_after_terminal_pause():
    snapshot = SimpleNamespace(created_at="2026-08-22T00:00:00Z", next=())

    assert _resume_starts_new_cycle(snapshot)


def test_resume_continues_pending_checkpoint_after_crash():
    snapshot = SimpleNamespace(
        created_at="2026-08-22T00:00:00Z",
        next=("execute_ready",),
    )

    assert not _resume_starts_new_cycle(snapshot)
