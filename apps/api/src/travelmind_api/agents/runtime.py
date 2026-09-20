from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


RoleProgressCallback = Callable[[str, str, str, int], None]
CancellationCheck = Callable[[], bool]


class WorkflowCancelled(RuntimeError):
    """Raised at a workflow boundary when the owning job was cancelled."""


@dataclass(frozen=True)
class WorkflowRuntime:
    """Non-serializable services injected into one workflow execution.

    Credentials, callbacks, database sessions, and clients belong here rather
    than in LangGraph state. The state can therefore be checkpointed without
    leaking execution-only objects or secrets.
    """

    run_id: str
    job_id: str | None = None
    owner_user_id: str | None = None
    progress_callback: RoleProgressCallback | None = None
    cancellation_check: CancellationCheck | None = None

    def check_cancelled(self) -> None:
        if self.cancellation_check is not None and self.cancellation_check():
            raise WorkflowCancelled(f"Workflow run {self.run_id} was cancelled")

    def emit_progress(
        self,
        role_name: str,
        title: str,
        description: str,
        progress_percent: int,
    ) -> None:
        self.check_cancelled()
        if self.progress_callback is not None:
            self.progress_callback(role_name, title, description, progress_percent)

