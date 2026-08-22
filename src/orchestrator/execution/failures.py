from enum import StrEnum

from pydantic import ValidationError

from orchestrator.domain.common import ExecutionStatus
from orchestrator.domain.results import WorkerResult
from orchestrator.verification.models import VerificationResult
from orchestrator.workspace.git import GitCommandError


class FailureClass(StrEnum):
    ENVIRONMENTAL = "environmental"
    TIMEOUT = "timeout"
    INVALID_STRUCTURED_RESPONSE = "invalid_structured_response"
    IMPLEMENTATION_FAILURE = "implementation_failure"
    INSUFFICIENT_CAPABILITY = "insufficient_capability"
    POLICY_PERMISSION = "policy_permission"
    INTEGRATION_CONFLICT = "integration_conflict"
    UNKNOWN = "unknown"


class FailureClassifier:
    def classify(
        self,
        *,
        error: Exception | None = None,
        result: WorkerResult | None = None,
        verification: VerificationResult | None = None,
    ) -> FailureClass:
        if isinstance(error, FileNotFoundError):
            return FailureClass.ENVIRONMENTAL
        if isinstance(error, PermissionError):
            return FailureClass.POLICY_PERMISSION
        if isinstance(error, ValidationError):
            return FailureClass.INVALID_STRUCTURED_RESPONSE
        if isinstance(error, GitCommandError) and "cherry-pick" in error.command:
            return FailureClass.INTEGRATION_CONFLICT
        if result is not None and result.status is ExecutionStatus.TIMED_OUT:
            return FailureClass.TIMEOUT
        if (
            result is not None
            and result.status is ExecutionStatus.SUCCEEDED
            and verification is not None
            and not verification.passed
        ):
            return FailureClass.IMPLEMENTATION_FAILURE

        text = " ".join(result.errors if result is not None else []).lower()
        if "missing required capability" in text or "cannot solve" in text:
            return FailureClass.INSUFFICIENT_CAPABILITY
        policy_terms = ("permission denied", "policy blocked", "blocked command")
        if any(term in text for term in policy_terms):
            return FailureClass.POLICY_PERMISSION
        if any(term in text for term in ("executable not found", "command not found")):
            return FailureClass.ENVIRONMENTAL
        return FailureClass.UNKNOWN
