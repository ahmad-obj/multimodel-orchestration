from pydantic import ValidationError

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.execution.failures import FailureClass, FailureClassifier
from orchestrator.verification.models import VerificationResult
from orchestrator.workspace.git import GitCommandError


def result(status=ExecutionStatus.FAILED, errors=None):
    return WorkerResult(
        execution_id="e",
        worker_id="w",
        task_id="t",
        status=status,
        summary="x",
        errors=errors or [],
    )


def test_failure_classifier_typed_cases():
    classifier = FailureClassifier()
    assert classifier.classify(error=FileNotFoundError()) is FailureClass.ENVIRONMENTAL
    assert (
        classifier.classify(result=result(ExecutionStatus.TIMED_OUT))
        is FailureClass.TIMEOUT
    )
    try:
        WorkerResult.model_validate({})
    except ValidationError as exc:
        assert (
            classifier.classify(error=exc)
            is FailureClass.INVALID_STRUCTURED_RESPONSE
        )

    verification = VerificationResult(passed=False, checks=[], summary="failed")
    assert (
        classifier.classify(
            result=result(ExecutionStatus.SUCCEEDED), verification=verification
        )
        is FailureClass.IMPLEMENTATION_FAILURE
    )
    assert (
        classifier.classify(
            result=result(errors=["cannot solve: missing required capability"])
        )
        is FailureClass.INSUFFICIENT_CAPABILITY
    )
    assert classifier.classify(error=PermissionError()) is FailureClass.POLICY_PERMISSION
    conflict = GitCommandError(["git", "cherry-pick", "abc"], 1, "", "conflict")
    assert classifier.classify(error=conflict) is FailureClass.INTEGRATION_CONFLICT
