from orchestrator.policies.approval import ApprovalRequest, ApprovalStatus


def test_approval_is_pending_by_default_and_scoped_to_candidates() -> None:
    request = ApprovalRequest(
        id="approval-1",
        job_id="job-1",
        task_id="T1",
        reason="paid escalation",
        candidate_worker_ids=["paid/worker"],
    )

    assert request.status is ApprovalStatus.PENDING
    assert request.candidate_worker_ids == ["paid/worker"]
