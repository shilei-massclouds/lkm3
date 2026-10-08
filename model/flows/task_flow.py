"""Task Flow"""

from typing import TYPE_CHECKING

from framework.contention import TASKPRIVATE_CV
from framework.engine import System, visibility

if TYPE_CHECKING:
    from kernel.task import Task


@visibility(TASKPRIVATE_CV)
class TaskFlow(System):
    """Synchronous task actions receive their environment through each signal."""

    def claim(self, task: Task) -> None:
        """Bind this flow instance to exactly one task."""
        assert not hasattr(self, "_task_owner"), (
            "TaskFlow instances cannot be shared between tasks"
        )
        self._task_owner = task
