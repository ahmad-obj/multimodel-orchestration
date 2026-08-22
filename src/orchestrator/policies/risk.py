from orchestrator.domain.tasks import TaskAnalysis, TaskPlan, TaskRisk


class RiskPolicy:
    LOW_CONFIDENCE_THRESHOLD = 0.70

    def requires_human_input(self, analysis: TaskAnalysis, plan: TaskPlan) -> bool:
        confidence = min(analysis.confidence, plan.confidence)
        return analysis.risk is TaskRisk.HIGH and confidence < self.LOW_CONFIDENCE_THRESHOLD
