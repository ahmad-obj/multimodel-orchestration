# V1 Acceptance Matrix

This matrix maps the approved Coding Orchestrator V1 success criteria to concrete implementation/test evidence. Final acceptance requires the normal test/lint gate plus the opt-in real-harness smoke gate.

| # | V1 criterion | Evidence |
|---|---|---|
| 1 | Vendor/model-neutral worker abstraction with Codex, Gemini and OpenCode | `src/orchestrator/domain/workers.py`, `src/orchestrator/workers/`, `tests/unit/workers/` |
| 2 | Dynamic capability-aware manager selection; no permanent Codex-as-manager rule | `src/orchestrator/selection/manager.py`, `selection/router.py`, manager selection tests |
| 3 | Free/included-first cost-aware worker routing; paid excluded automatically | `src/orchestrator/capabilities/scoring.py`, `policies/cost.py`, `scheduling/scheduler.py`, routing/scheduler tests |
| 4 | Structured task analysis and manager-produced dependency DAG | `analysis/task_analyzer.py`, `planning/decomposer.py`, `domain/tasks.py`, planning tests |
| 5 | Deterministic DAG/dependency/parallel-write validation and bounded repair | `planning/validator.py`, `planning/service.py`, validator/planning tests |
| 6 | Durable shared state, events, artifacts and restart-safe SQLite persistence | `persistence/`, `artifacts/`, `observability/`, persistence tests |
| 7 | Real concurrent execution bounded by per-worker parallel capacity | `execution/executor.py`, scheduler/executor tests |
| 8 | Modifying workers isolated in Git worktrees; no direct source-checkout mutation | `workspace/worktrees.py`, `workspace/git.py`, worktree executor tests |
| 9 | Worker output must be verified/accepted before durable task completion | `verification/`, `execution/outcomes.py`, verification/outcome tests |
| 10 | Failure classification drives bounded retry/reassignment/escalation; no blind retries | `execution/failures.py`, `policies/escalation.py`, failure/escalation tests |
| 11 | Paid escalation pauses for explicit task-scoped approval; no global paid switch | `policies/approval.py`, `jobs/service.py`, approval/supervisor/resume tests |
| 12 | LangGraph is replaceable runtime infrastructure only; durable checkpoint resume does not repeat completed work | `runtime/`, `tests/runtime/test_boundary.py`, crash/restart and resume-strategy tests |
| 13 | Accepted commits integrate topologically into an isolated local branch/worktree, final verification runs, and no push occurs automatically | `integration/service.py`, `jobs/engine.py`, integration tests, `tests/e2e/test_fake_job.py` |

## Mandatory automated gate

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

The full fake-worker E2E path must use real Git, filesystem, SQLite and LangGraph while avoiding real model calls.

## Real harness gate

Real harness invocation is deliberately excluded from the normal suite. Run only when free/included quota use is acceptable:

```bash
ORCHESTRATOR_REAL_HARNESS_TESTS=1 \
uv run pytest -m real_harness tests/real_harness -q
```

The smoke gate must confirm for each available harness:

- executable/policy interface is healthy;
- a read-only structured request can complete;
- selected model is propagated by the adapter;
- network and nested-worker access remain denied;
- no repository files are modified.

If a configured free model is unavailable, override it with the documented environment variable rather than changing routing architecture.

## V1 non-goals

- automatic push or PR creation;
- global paid-model authorization;
- nested worker spawning by harnesses;
- manager migration during a running job;
- UI/dashboard;
- distributed/cloud execution;
- replacing the orchestrator's policy logic with LangGraph-specific logic.
