"""Scheduling initialized by the running boot task and entered via schedule()."""

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from greenlet import GreenletExit, getcurrent, greenlet

from framework.engine import Signal, System, requires_cv
from framework.sync import ContentionVector

if TYPE_CHECKING:
    from kernel.task import Task


@requires_cv(ContentionVector(zero=True, local_irq=1, local_tasks=1))
@dataclass
class Scheduler(System):
    runq: deque[Task] = field(default_factory=deque, init=False, repr=False)
    current: Task | None = field(default=None, init=False, repr=False)
    idle: Task | None = field(default=None, init=False, repr=False)
    context: greenlet | None = field(default=None, init=False, repr=False)
    _prepared: list[Task] = field(default_factory=list, init=False, repr=False)
    _closing: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def setup(self, sig: Signal):
        from kernel.task import TaskState

        if self.context is not None:
            raise RuntimeError("scheduler has already been initialized")
        task = sig.env.task
        if (
            task is None
            or task.pid != 0
            or sig.env is not task.env
            or task.state is not TaskState.RUNNING
            or task.greenlet is not getcurrent()
        ):
            raise RuntimeError("scheduler setup requires the running task 0")
        if task.scheduler is not None:
            raise RuntimeError("task 0 already belongs to a scheduler")
        self.idle = self.current = task
        self.context = greenlet(self._dispatch, parent=task.greenlet)
        task.scheduler = self

    def _require_current(self, sig: Signal) -> Task:
        from kernel.task import TaskState

        if self.context is None:
            raise RuntimeError("scheduler has not been initialized")
        if self._closing or self._closed:
            raise RuntimeError("scheduler has been stopped")
        task = sig.env.task
        if (
            task is None
            or task is not self.current
            or task.scheduler is not self
            or sig.env is not task.env
            or task.state is not TaskState.RUNNING
            or getcurrent() is not task.greenlet
        ):
            raise RuntimeError("operation must be called by the current task")
        return task

    def register(self, task: Task, sig: Signal):
        self._require_current(sig)
        if task.scheduler is not self or task.pid == 0:
            raise RuntimeError("ordinary task must belong to this scheduler")
        self._prepared.append(task)

    def enqueue(self, sig: Signal):
        from kernel.task import Task, TaskState

        self._require_current(sig)
        task = sig.args["task"]
        if not isinstance(task, Task) or task.scheduler is not self:
            raise RuntimeError("task belongs to a different scheduler")
        if task is self.idle:
            raise RuntimeError("idle task cannot be queued as an ordinary task")
        if task.greenlet is None:
            raise RuntimeError("task has not been set up")
        if task.greenlet.dead or task.state in (
            TaskState.FINISHED,
            TaskState.CANCELLED,
        ):
            raise RuntimeError("task has already ended")
        if task.state in (TaskState.READY, TaskState.RUNNING):
            raise RuntimeError("task is already queued or running")
        if task.state not in (TaskState.PREPARED, TaskState.BLOCKED):
            raise RuntimeError("task is not ready to be enabled")
        task.state = TaskState.READY
        self.runq.append(task)

    def schedule(self, sig: Signal):
        from kernel.task import TaskState

        task = self._require_current(sig)
        blocked = sig.args.get("block", False)
        if task is self.idle and blocked:
            raise RuntimeError("idle task cannot block")
        task.state = TaskState.BLOCKED if blocked else TaskState.READY
        if task is not self.idle and not blocked:
            self.runq.append(task)
        context = self.context
        assert context is not None
        context.switch()

    def _dispatch(self):
        """Enter only from a task's schedule call; empty queues select task 0."""
        from kernel.task import TaskState

        try:
            while True:
                task = self.runq.popleft() if self.runq else self.idle
                assert task is not None
                self.current = task
                task.state = TaskState.RUNNING
                context = task.greenlet
                assert context is not None
                context.switch()
                if context.dead:
                    task.state = TaskState.FINISHED
                    self._prepared = [
                        item for item in self._prepared if item is not task
                    ]
        except BaseException as error:
            if not self._closing:
                self._cancel_tasks(error)
            raise

    def _cancel_tasks(self, error: BaseException | None) -> BaseException | None:
        """Unwind prepared and suspended tasks while preserving the first error."""
        from kernel.task import TaskState

        self._closing = True
        self.current = None
        self.runq.clear()
        for task in self._prepared:
            context = task.greenlet
            if context is not None and not context.dead:
                try:
                    # Cleanup must return here, rather than restart the dispatcher.
                    context.parent = getcurrent()
                    context.throw(GreenletExit)
                except BaseException as cleanup_error:  # noqa: BLE001
                    # Finish cancelling peers even after an exit signal in cleanup.
                    if error is None:
                        error = cleanup_error
                    else:
                        error.add_note(f"cleanup failed for {task}: {cleanup_error!r}")
            task.state = TaskState.CANCELLED
        self._prepared.clear()
        if self.idle is not None:
            self.idle.state = TaskState.CANCELLED
        self._closed = True
        return error

    def close(self, error: BaseException | None = None):
        """Clean up when the boot stack exits, including an explicit derivation stop."""
        if self._closed:
            return
        if self.idle is None or getcurrent() is not self.idle.greenlet:
            raise RuntimeError("scheduler cleanup requires task 0's context")
        cleanup_error = self._cancel_tasks(error)
        context = self.context
        try:
            if context is not None and not context.dead:
                context.throw(GreenletExit)
        finally:
            self._closing = False
        if error is None and cleanup_error is not None:
            raise cleanup_error
