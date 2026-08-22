from orchestrator.domain.events import EventType, OrchestratorEvent


class EventRenderer:
    def render(self, event: OrchestratorEvent) -> str:
        p = event.payload
        if event.type is EventType.MANAGER_SELECTED:
            return f"[manager] {event.worker_id or p.get('worker_id','?')} selected (score {p.get('score','?')})"
        if event.type is EventType.TASK_ASSIGNED:
            return f"[task {event.task_id}] assigned to {event.worker_id or p.get('worker_id','?')}"
        if event.type is EventType.WORKER_COMPLETED:
            return f"[task {event.task_id}] completed (confidence {p.get('confidence','?')})"
        return f"[{event.type.value}] {event.task_id or event.job_id}"
