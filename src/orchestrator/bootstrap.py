from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from orchestrator.analysis.task_analyzer import TaskAnalyzer
from orchestrator.artifacts.store import ArtifactStore
from orchestrator.capabilities.learning import PerformanceLearningService
from orchestrator.capabilities.scoring import WorkerScorer
from orchestrator.config import AppPaths, Settings
from orchestrator.execution.accepted import AcceptedCommitStore
from orchestrator.execution.executor import TaskExecutor
from orchestrator.execution.failures import FailureClassifier
from orchestrator.execution.outcomes import TaskOutcomeProcessor
from orchestrator.integration.service import IntegrationService
from orchestrator.jobs.engine import JobEngine
from orchestrator.observability.events import EventBus
from orchestrator.persistence.db import Database
from orchestrator.persistence.job_store import JobStore
from orchestrator.persistence.repositories import (
    ArtifactRepository,
    AttemptRepository,
    CostUsageRepository,
    DecisionRepository,
    EventRepository,
    TaskRepository,
    VerificationRepository,
    WorkerPerformanceRepository,
    WorkerRepository,
)
from orchestrator.planning.decomposer import TaskDecomposer
from orchestrator.planning.service import PlanningService
from orchestrator.policies.cost import CostPolicy
from orchestrator.policies.escalation import EscalationPolicy
from orchestrator.runtime.langgraph import LangGraphRuntime
from orchestrator.scheduling.scheduler import Scheduler
from orchestrator.selection.manager import ManagerSelector
from orchestrator.verification.reviewers import StructuredReviewProvider
from orchestrator.verification.service import VerificationService
from orchestrator.workers.base import WorkerAdapter
from orchestrator.workers.codex import CodexAdapter
from orchestrator.workers.gemini import GeminiAdapter
from orchestrator.workers.opencode import OpenCodeAdapter
from orchestrator.workers.registry import WorkerRegistry
from orchestrator.workspace.git import GitClient
from orchestrator.workspace.worktrees import WorktreeManager


class OrchestratorApplication:
    def __init__(
        self,
        *,
        paths: AppPaths,
        database: Database,
        registry: WorkerRegistry,
        jobs: JobStore,
        tasks: TaskRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactRepository,
        decisions: DecisionRepository,
        verifications: VerificationRepository,
        events: EventRepository,
        performance: WorkerPerformanceRepository,
        event_bus: EventBus,
        runtime: LangGraphRuntime,
        engine: JobEngine,
    ) -> None:
        self.paths = paths
        self.database = database
        self.registry = registry
        self.jobs = jobs
        self.tasks = tasks
        self.attempts = attempts
        self.artifacts = artifacts
        self.decisions = decisions
        self.verifications = verifications
        self.events = events
        self.performance = performance
        self.event_bus = event_bus
        self.runtime = runtime
        self.engine = engine

    async def close(self) -> None:
        await self.database.dispose()


async def build_application(
    *,
    paths: AppPaths | None = None,
    settings: Settings | None = None,
    adapters: Mapping[str, WorkerAdapter] | None = None,
) -> OrchestratorApplication:
    paths = paths or AppPaths.from_environment()
    settings = settings or Settings.load(paths)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.worktrees_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)

    database = Database(paths.database)
    await database.initialize()

    workers = WorkerRepository(database)
    jobs = JobStore(database)
    tasks = TaskRepository(database)
    attempts = AttemptRepository(database)
    artifacts = ArtifactRepository(database)
    decisions = DecisionRepository(database)
    verifications = VerificationRepository(database)
    costs = CostUsageRepository(database)
    events = EventRepository(database)
    performance = WorkerPerformanceRepository(database)
    event_bus = EventBus(events)

    adapter_map: dict[str, WorkerAdapter] = dict(
        adapters
        or {
            "codex": CodexAdapter(),
            "gemini": GeminiAdapter(),
            "opencode": OpenCodeAdapter(),
        }
    )
    profiles = [configured.to_profile() for configured in settings.workers]
    registry = WorkerRegistry(profiles, adapter_map)

    learning = PerformanceLearningService(performance, attempts, tasks, events)
    history = await learning.load([profile.id for profile in profiles])
    scorer = WorkerScorer(history=history)
    cost_policy = CostPolicy(allow_paid=False)

    analyzer = TaskAnalyzer(registry)
    decomposer = TaskDecomposer(adapter_map)
    planning = PlanningService(
        analyzer=analyzer,
        decomposer=decomposer,
        manager_selector=ManagerSelector(scorer=scorer, cost_policy=cost_policy),
    )
    scheduler = Scheduler(registry, scorer=scorer, cost_policy=cost_policy)

    git = GitClient()
    worktrees = WorktreeManager(git, paths.worktrees_dir)
    artifact_store = ArtifactStore(paths.data_dir)
    review_provider = StructuredReviewProvider(
        registry,
        repo_path=None,
        job_repository=jobs,
        cost_policy=cost_policy,
    )
    verification = VerificationService(
        artifact_store,
        review_provider=review_provider,
        verification_repository=verifications,
        event_bus=event_bus,
    )
    failure_classifier = FailureClassifier()
    escalation = EscalationPolicy(scorer=scorer, cost_policy=cost_policy)
    outcome_processor = TaskOutcomeProcessor(
        registry=registry,
        verification_service=verification,
        failure_classifier=failure_classifier,
        escalation_policy=escalation,
        attempt_repository=attempts,
        task_repository=tasks,
        job_repository=jobs,
        decision_repository=decisions,
        performance_repository=performance,
        event_bus=event_bus,
    )
    executor = TaskExecutor(
        registry,
        artifact_store=artifact_store,
        attempt_repository=attempts,
        artifact_repository=artifacts,
        cost_repository=costs,
        event_bus=event_bus,
        worktree_manager=worktrees,
        git_client=git,
        outcome_processor=outcome_processor,
    )
    runtime = LangGraphRuntime(
        database,
        scheduler=scheduler,
        executor=executor,
        jobs=jobs,
        tasks=tasks,
    )
    accepted = AcceptedCommitStore(attempts, events)
    integration = IntegrationService(
        git,
        integration_root=paths.worktrees_dir / "integration",
        verification_service=None,
    )
    engine = JobEngine(
        registry=registry,
        worker_repository=workers,
        job_repository=jobs,
        task_repository=tasks,
        planning=planning,
        runtime=runtime,
        accepted_commits=accepted,
        integration=integration,
        final_verifier=verification,
        event_bus=event_bus,
        event_repository=events,
    )

    return OrchestratorApplication(
        paths=paths,
        database=database,
        registry=registry,
        jobs=jobs,
        tasks=tasks,
        attempts=attempts,
        artifacts=artifacts,
        decisions=decisions,
        verifications=verifications,
        events=events,
        performance=performance,
        event_bus=event_bus,
        runtime=runtime,
        engine=engine,
    )
