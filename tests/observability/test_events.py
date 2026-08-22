from orchestrator.domain.events import EventType, OrchestratorEvent
from orchestrator.observability.events import EventBus


def test_event_contract_contains_v1_lifecycle_events():
    expected = {"job_created","analysis_started","analysis_completed","manager_selected","plan_created","plan_validation_failed","task_assigned","worker_started","worker_completed","worker_failed","task_accepted","task_rejected","task_reassigned","verification_started","verification_failed","verification_passed","integration_started","integration_completed","job_completed","job_failed","human_input_required","approval_required"}
    assert expected <= {event.value for event in EventType}
    event=OrchestratorEvent(type=EventType.JOB_CREATED,job_id="job-1",payload={"repo":"/tmp/x"})
    assert event.job_id == "job-1"


class Repo:
    def __init__(self): self.events=[]
    async def append(self,event): self.events.append(event)
    async def list_for_job(self,job_id): return [e for e in self.events if e.job_id==job_id]


async def test_event_bus_persists_before_notifying():
    repo=Repo(); seen=[]; bus=EventBus(repo)
    bus.subscribe(lambda e: seen.append((len(repo.events),e)))
    event=OrchestratorEvent(type=EventType.JOB_CREATED,job_id="job-2",payload={})
    await bus.publish(event)
    assert [(n,e.type) for n,e in seen] == [(1,EventType.JOB_CREATED)]
