"""Select and switch tasks on the calling task's stack."""

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from greenlet import getcurrent

from framework.engine import Signal, System, TaskLocalEnv, requires_cv
from framework.sync import ContentionVector

if TYPE_CHECKING:
    from kernel.task import Task


@requires_cv(ContentionVector(zero=True, local_irq=1, local_tasks=1))
@dataclass
class Scheduler(System):
    runq: deque[Task] = field(default_factory=deque, init=False, repr=False)
    current: Task | None = field(default=None, init=False, repr=False)
    idle: Task | None = field(default=None, init=False, repr=False)

    def setup(self, sig: Signal):
        from kernel.task import TaskState

        assert self.idle is None, "scheduler has already been initialized"
        task = sig.env.task
        assert (
            task is not None
            and task.pid == 0
            and sig.env is task.env
            and task.state is TaskState.RUNNING
            and task.greenlet is getcurrent()
        ), "scheduler setup requires the running task 0"
        assert task.scheduler is None, "task 0 already belongs to a scheduler"
        self.idle = self.current = task
        task.scheduler = self

    def _require_current(self, env: TaskLocalEnv) -> Task:
        from kernel.task import TaskState

        assert self.idle is not None, "scheduler has not been initialized"
        task = env.task
        assert (
            task is not None
            and task is self.current
            and task.scheduler is self
            and env is task.env
            and task.state is TaskState.RUNNING
            and getcurrent() is task.greenlet
        ), "operation must be called by the current task"
        return task

    def enqueue(self, sig: Signal):
        from kernel.task import Task, TaskState

        self._require_current(sig.env)
        task = sig.args["task"]
        assert isinstance(task, Task) and task.scheduler is self, (
            "task belongs to a different scheduler"
        )
        assert task is not self.idle, "idle task cannot be queued as an ordinary task"
        assert task.greenlet is not None, "task has not been set up"
        assert not task.greenlet.dead and task.state is not TaskState.FINISHED, (
            "task has already ended"
        )
        assert task.state not in (TaskState.READY, TaskState.RUNNING), (
            "task is already queued or running"
        )
        assert task.state in (TaskState.PREPARED, TaskState.BLOCKED), (
            "task is not ready to be enabled"
        )
        task.state = TaskState.READY
        self.runq.append(task)

    def _select_next(self) -> Task:
        from kernel.task import TaskState

        task = self.runq.popleft() if self.runq else self.idle
        assert task is not None and task.state is TaskState.READY
        assert task.greenlet is not None and not task.greenlet.dead
        self.current = task
        task.state = TaskState.RUNNING
        return task

    def schedule(self, sig: Signal):
        from kernel.task import TaskState

        task = self._require_current(sig.env)
        blocked = sig.args.get("block", False)
        assert task is not self.idle or not blocked, "idle task cannot block"
        task.state = TaskState.BLOCKED if blocked else TaskState.READY
        if task is not self.idle and not blocked:
            self.runq.append(task)
        next_task = self._select_next()
        if next_task is not task:
            assert next_task.greenlet is not None
            next_task.greenlet.switch()
        # This call returns only when another task has selected its caller again.
        self._require_current(sig.env)

    def finish(self, env: TaskLocalEnv):
        """Select the task that receives control when this task's greenlet returns."""
        from kernel.task import TaskState

        task = self._require_current(env)
        assert task is not self.idle, "idle task cannot exit through the scheduler"
        task.state = TaskState.FINISHED
        next_task = self._select_next()
        assert task.greenlet is not None and next_task.greenlet is not None
        # Returning makes the source greenlet dead and resumes the target directly.
        task.greenlet.parent = next_task.greenlet
