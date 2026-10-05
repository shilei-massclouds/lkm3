"""Tasks with independent contention state and greenlet call stacks."""

from copy import copy
from enum import Enum, auto

from greenlet import getcurrent, greenlet

from flows.task_flow import TaskFlow
from framework.engine import Signal, System, TaskLocalEnv, requires_cv
from framework.scheduler import Scheduler
from framework.sync import ContentionVector


class TaskState(Enum):
    NEW = auto()
    PREPARED = auto()
    READY = auto()
    RUNNING = auto()
    BLOCKED = auto()
    FINISHED = auto()
    CANCELLED = auto()


@requires_cv(ContentionVector(zero=True, local_irq=1, local_tasks=1))
class Task(System):
    def __init__(
        self,
        name: str,
        flow: TaskFlow,
        action: str,
        cv: ContentionVector,
        scheduler: Scheduler | None = None,
        *,
        pid: int | None = None,
    ):
        super().__init__()
        self.name = name
        self.pid = pid
        self.flow = flow
        self.action = action
        self.scheduler = scheduler
        self.env = TaskLocalEnv(copy(cv), task=self)
        self.greenlet: greenlet | None = None
        self.state = TaskState.NEW

    def __repr__(self):
        label = self.name if self.pid is None else f"{self.pid}, {self.name}"
        return f"Task({label})"

    def bind_current(self):
        """Task 0 adopts the already running stack, before a scheduler exists."""
        if self.pid != 0 or self.scheduler is not None:
            raise RuntimeError("only task 0 can start before scheduler initialization")
        if self.greenlet is not None:
            raise RuntimeError("task has already been set up")
        self.greenlet = getcurrent()
        self.state = TaskState.RUNNING

    def start(self):
        self.bind_current()
        try:
            self._run()
        except BaseException as error:
            if self.scheduler is not None:
                self.scheduler.close(error)
            self.state = TaskState.CANCELLED
            raise
        else:
            if self.scheduler is not None:
                self.scheduler.close()
            self.state = TaskState.FINISHED

    def require_scheduler(self) -> Scheduler:
        if self.scheduler is None:
            raise RuntimeError("task has no initialized scheduler")
        return self.scheduler

    def setup(self, sig: Signal):
        if self.greenlet is not None:
            raise RuntimeError("task has already been set up")
        scheduler = self.require_scheduler()
        scheduler.register(self, sig)
        self.greenlet = greenlet(self._run, parent=scheduler.context)
        self.state = TaskState.PREPARED

    def enable(self, sig: Signal):
        self.drive(sig.env, self.require_scheduler(), "enqueue", task=self)

    def _run(self):
        self.drive(self.env, self.flow, self.action)


class KernelInitTask(Task):
    pass
