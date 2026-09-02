# Multimodal Orchestration

> A local-first, vendor-neutral control plane for coordinating autonomous coding agents.

The project explores a practical problem: how do multiple AI coding workers share work, preserve context, recover from failure, and produce results that can actually be verified?

> [!NOTE]
> The active v1 implementation currently lives on [`feat/v1-implementation`](https://github.com/ahmad-obj/multimodel-orchestration/tree/feat/v1-implementation). The default branch is being kept deliberately small until the implementation reaches its promotion gate.

## What it coordinates

- **Multiple workers** — Codex CLI, Gemini CLI, and OpenCode behind capability profiles
- **Deterministic routing** — worker selection based on task needs and recorded performance
- **Dependency-aware execution** — jobs decomposed into tasks with explicit prerequisites
- **Shared state** — jobs, attempts, artifacts, decisions, verification runs, costs, and events persisted in SQLite
- **Crash recovery** — checkpointed workflows designed to resume rather than restart blindly
- **Verification** — outputs and decisions are recorded as first-class workflow data

## Architecture

```text
request
  └─> plan job
       └─> build task graph
            └─> score + select worker
                 └─> execute in isolated workspace
                      └─> collect artifacts
                           └─> verify + persist result
```

| Layer | Responsibility |
| :-- | :-- |
| CLI / job service | Accept work, inspect progress, and control execution |
| LangGraph runtime | Drive the resumable orchestration lifecycle |
| Worker adapters | Present different coding harnesses through one contract |
| Workspace isolation | Keep concurrent attempts from corrupting one another |
| Async SQLite state | Preserve task, decision, artifact, cost, and event history |
| Verification | Decide whether an attempt is usable before advancing the graph |

## Stack

`Python 3.12+` · `LangGraph` · `SQLAlchemy` · `aiosqlite` · `Typer` · `Pydantic` · `pytest`

## Direction

The goal is not to create another chat wrapper. It is to build the boring, reliable coordination layer needed when several agents must work on the same software project without constant human re-prompting.

