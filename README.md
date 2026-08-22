# Multimodal Orchestration

Local-first, vendor-neutral orchestration for heterogeneous coding agents. V1 treats a worker as the combination of **model + harness + tools + permissions + cost + observed performance**, then selects managers and workers by capability rather than hard-coding one provider as the boss.

## V1 flow

```text
request
  -> bounded repository analysis
  -> capability requirements
  -> dynamic manager selection
  -> manager-produced task DAG
  -> deterministic plan validation
  -> cost/capability-aware scheduling
  -> isolated worker execution
  -> verification + review
  -> retry/reassign/escalate
  -> deterministic Git integration
  -> final repository verification
```

Initial harnesses: Codex CLI, Gemini CLI, and OpenCode. LangGraph is used only as the replaceable durable execution runtime under `src/orchestrator/runtime/`; orchestration policy lives outside it.

## Install

```bash
uv sync
```

Configure workers in:

```text
$XDG_CONFIG_HOME/multimodal-orchestration/workers.yaml
```

If that file is absent, `config/workers.example.yaml` is used.

Persistent state lives under:

```text
$XDG_DATA_HOME/multimodal-orchestration/
  orchestrator.db
  artifacts/
  worktrees/
  logs/
```

## CLI

```bash
uv run orchestrate --help
uv run orchestrate workers
uv run orchestrate run /path/to/repo "implement the requested change"
uv run orchestrate jobs
uv run orchestrate job <job-id>
uv run orchestrate resume <job-id>
uv run orchestrate cancel <job-id>
uv run orchestrate approve <job-id> <task-id> <worker-id>
uv run orchestrate reject <job-id> <task-id>
```

V1 never automatically pushes or opens a PR. Modifying workers run in orchestrator-owned Git worktrees; accepted commits are integrated into a separate local integration worktree.

## Safety model

- Paid workers are excluded from automatic routing; paid escalation requires explicit task-scoped approval.
- Nested/subagent spawning is denied by default; only the central orchestrator schedules workers.
- Network access is denied by default.
- Codex uses read-only/workspace-write sandboxing, disables web search and nested multi-agent features, and honors the selected worker model.
- Gemini runs headlessly with an orchestrator-generated `--policy` file. The policy is fail-closed and allows only requested reads/writes/shell prefixes/network/subagent capabilities.
- OpenCode receives an execution-scoped permission config through `OPENCODE_CONFIG_CONTENT`, including explicit denial of external directories, network, subagents, and unapproved shell commands.
- Worker success is not acceptance: verification/review must pass before a task becomes `COMPLETED`.

## Verification

Normal local gate:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Real harness tests are opt-in and may consume included/free model quota:

```bash
ORCHESTRATOR_REAL_HARNESS_TESTS=1 \
uv run pytest -m real_harness tests/real_harness -q
```

Optional model overrides:

```bash
ORCHESTRATOR_CODEX_MODEL=default
ORCHESTRATOR_GEMINI_MODEL=auto
ORCHESTRATOR_OPENCODE_MODEL=opencode/mimo-v2.5-free
```

The real-harness smoke test is read-only, denies network/subagents, checks structured output, and verifies the repository remains unchanged.

See `docs/v1-acceptance.md` for the V1 acceptance matrix.
