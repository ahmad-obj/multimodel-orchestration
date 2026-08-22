from pydantic import BaseModel

from orchestrator.domain.tasks import TaskAnalysis, TaskPlan
from orchestrator.planning.validator import PlanValidationError, PlanValidator
from orchestrator.policies.risk import RiskPolicy
from orchestrator.selection.manager import ManagerSelector
from orchestrator.selection.router import ManagerRouter


class PlannedJob(BaseModel):
    analysis: TaskAnalysis
    manager_worker_id: str
    manager_selection_reason: str
    plan: TaskPlan
    plan_attempts: int
    requires_human_input: bool = False
    human_question: str | None = None


class PlanningFailedError(RuntimeError):
    pass


class PlanningService:
    def __init__(
        self,
        *,
        analyzer,
        decomposer,
        manager_selector: ManagerSelector | None = None,
        router_factory=None,
        validator: PlanValidator | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.analyzer = analyzer
        self.decomposer = decomposer
        self.manager_selector = manager_selector or ManagerSelector()
        self.router_factory = router_factory
        self.validator = validator or PlanValidator()
        self.risk_policy = risk_policy or RiskPolicy()

    async def plan(self, objective: str, repository_summary, registry) -> PlannedJob:
        analysis = await self.analyzer.analyze(objective, repository_summary)
        selection = self.manager_selector.rank(analysis, registry.available())
        if not selection.ranked:
            raise PlanningFailedError("no eligible manager")
        chosen = selection.ranked[0]
        reason = chosen.reason
        if selection.needs_tiebreak:
            router = self.router_factory(registry) if self.router_factory else ManagerRouter(registry)
            decision = await router.break_tie(analysis, selection.ranked)
            chosen = next(item for item in selection.ranked if item.worker.profile.id == decision.worker_id)
            reason = f"AI tie-break: {decision.reason}"
        previous = None
        feedback = None
        for attempt in range(1, 4):
            plan = await self.decomposer.create_plan(
                chosen.worker,
                objective,
                analysis,
                repository_summary,
                repair_feedback=feedback,
                previous_plan=previous,
            )
            try:
                self.validator.validate(plan)
            except PlanValidationError as exc:
                previous = plan
                feedback = [issue.model_dump() for issue in exc.errors]
                continue
            requires_human = self.risk_policy.requires_human_input(analysis, plan)
            question = None
            if requires_human:
                question = plan.human_question or "The plan is high-risk and low-confidence. Provide clarification before execution."
            return PlannedJob(
                analysis=analysis,
                manager_worker_id=chosen.worker.profile.id,
                manager_selection_reason=reason,
                plan=plan,
                plan_attempts=attempt,
                requires_human_input=requires_human,
                human_question=question,
            )
        raise PlanningFailedError("manager failed to produce a valid plan after 3 attempts")
