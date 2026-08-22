from collections import defaultdict, deque
from pathlib import PurePosixPath

from pydantic import BaseModel

from orchestrator.domain.tasks import TaskPlan


class PlanIssue(BaseModel):
    code: str
    task_id: str | None = None
    message: str


class PlanValidationError(ValueError):
    def __init__(self, errors: list[PlanIssue]):
        super().__init__("; ".join(f"{e.code}: {e.message}" for e in errors))
        self.errors = errors


class PlanValidator:
    def validate(self, plan: TaskPlan) -> TaskPlan:
        errors: list[PlanIssue] = []
        ids = [task.id for task in plan.subtasks]
        seen: set[str] = set()
        duplicates: set[str] = set()
        for task_id in ids:
            if task_id in seen:
                duplicates.add(task_id)
            seen.add(task_id)
        for task_id in sorted(duplicates):
            errors.append(
                PlanIssue(
                    code="duplicate_task_id",
                    task_id=task_id,
                    message="task ID appears more than once",
                )
            )
        id_set = set(ids)
        for task in plan.subtasks:
            for dep in task.dependencies:
                if dep not in id_set:
                    errors.append(
                        PlanIssue(
                            code="missing_dependency",
                            task_id=task.id,
                            message=f"missing dependency {dep}",
                        )
                    )
            if not task.read_only and not {"filesystem", "git"}.issubset(task.required_tools):
                errors.append(
                    PlanIssue(
                        code="invalid_modification_requirements",
                        task_id=task.id,
                        message="modifying tasks require filesystem and git tools",
                    )
                )

        by_group: dict[str, list] = defaultdict(list)
        for task in plan.subtasks:
            if task.preferred_parallel_group:
                by_group[task.preferred_parallel_group].append(task)
        for group, tasks in by_group.items():
            modifying = [t for t in tasks if not t.read_only]
            if len(modifying) < 2:
                continue
            for i, left in enumerate(modifying):
                for right in modifying[i + 1 :]:
                    if not left.write_paths or not right.write_paths:
                        errors.append(
                            PlanIssue(
                                code="conflicting_parallel_writes",
                                task_id=left.id,
                                message=f"parallel group {group} has unknown write scope",
                            )
                        )
                        continue
                    left_paths = {str(PurePosixPath(p)) for p in left.write_paths}
                    right_paths = {str(PurePosixPath(p)) for p in right.write_paths}
                    if left_paths & right_paths:
                        errors.append(
                            PlanIssue(
                                code="conflicting_parallel_writes",
                                task_id=left.id,
                                message=f"parallel group {group} overlaps write paths",
                            )
                        )

        if not duplicates:
            indegree = {task_id: 0 for task_id in ids}
            edges: dict[str, list[str]] = defaultdict(list)
            for task in plan.subtasks:
                for dep in task.dependencies:
                    if dep in indegree:
                        edges[dep].append(task.id)
                        indegree[task.id] += 1
            q = deque([task_id for task_id, degree in indegree.items() if degree == 0])
            visited = 0
            while q:
                current = q.popleft()
                visited += 1
                for nxt in edges[current]:
                    indegree[nxt] -= 1
                    if indegree[nxt] == 0:
                        q.append(nxt)
            if visited != len(ids):
                errors.append(
                    PlanIssue(code="cycle", message="task dependency graph contains a cycle")
                )
        if errors:
            raise PlanValidationError(errors)
        return plan

    def topological_order(self, plan: TaskPlan) -> list[str]:
        self.validate(plan)
        indegree = {t.id: len(t.dependencies) for t in plan.subtasks}
        edges: dict[str, list[str]] = defaultdict(list)
        for task in plan.subtasks:
            for dep in task.dependencies:
                edges[dep].append(task.id)
        q = deque([task_id for task_id, degree in indegree.items() if degree == 0])
        order: list[str] = []
        while q:
            current = q.popleft()
            order.append(current)
            for nxt in edges[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    q.append(nxt)
        return order
