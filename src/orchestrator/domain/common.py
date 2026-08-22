from enum import StrEnum


class CostClass(StrEnum):
    FREE = "free"
    INCLUDED = "included"
    CHEAP = "cheap"
    PAID = "paid"


class WorkerStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
