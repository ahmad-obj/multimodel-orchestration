from orchestrator.domain.events import EventType, OrchestratorEvent


class EventRenderer:
    def render(self, event: OrchestratorEvent) -> str:
        p = event.payload
        if event.type is EventType.MANAGER_SELECTED:
            worker_id = event.worker_id or p.get("worker_id", "?")
            score = p.get("score", "?")
            return f"[manager] {worker_id} selected (score {score})"
        if event.type is EventType.TASK_ASSIGNED:
            return (
                f"[task {event.task_id}] assigned to {event.worker_id or p.get('worker_id', '?')}"
            )
        if event.type is EventType.WORKER_COMPLETED:
            return f"[task {event.task_id}] completed (confidence {p.get('confidence', '?')})"
        return f"[{event.type.value}] {event.task_id or event.job_id}"
