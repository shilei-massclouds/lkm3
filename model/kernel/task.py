"""Tasks with independent contention state and greenlet call stacks."""

from copy import copy
from enum import Enum, auto

from greenlet import getcurrent, greenlet

from flows.task_flow import TaskFlow
from framework.engine import Signal, System, TaskLocalEnv, requires_cv
from framework.scheduler import Scheduler
from framework.sync import EXCLUSIVE_CV, ContentionVector


class TaskState(Enum):
    NEW = auto()
    PREPARED = auto()
    READY = auto()
    RUNNING = auto()
    BLOCKED = auto()
    FINISHED = auto()


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
        flow.claim(self)
        self.action = action
        self.scheduler = scheduler
        self.env = TaskLocalEnv(copy(cv), task=self)
        self.greenlet: greenlet | None = None
        self.state = TaskState.NEW

    def __repr__(self):
        label = self.name if self.pid is None else f"{self.pid}, {self.name}"
        return f"Task({label})"

    def require_scheduler(self) -> Scheduler:
        assert self.scheduler is not None, "task has no initialized scheduler"
        return self.scheduler

    def setup(self, sig: Signal):
        assert self.greenlet is None, "task has already been set up"
        scheduler = self.require_scheduler()
        scheduler._require_current(sig.env)
        assert self.pid != 0, "task 0 must adopt its existing stack"
        assert scheduler.idle is not None and scheduler.idle.greenlet is not None
        self.greenlet = greenlet(self._run, parent=scheduler.idle.greenlet)
        self.state = TaskState.PREPARED

    def enable(self, sig: Signal):
        self.drive(sig.env, self.require_scheduler(), "enqueue", task=self)

    def _run(self, _previous_result: object = None):
        # A finishing task can start this greenlet by returning its result to it.
        self.drive(self.env, self.flow, self.action)
        if self.pid != 0:
            self.require_scheduler().finish(self.env)


class BootInitTask(Task):
    def __init__(self):
        from flows.boot_init_flow import BootInitFlow

        super().__init__(
            name="boot_init",
            pid=0,
            flow=BootInitFlow(),
            action="arch_boot",
            cv=EXCLUSIVE_CV,
        )

    def start(self, sig: Signal):
        assert self.scheduler is None
        assert self.greenlet is None, "task has already been started"

        self.greenlet = getcurrent()
        self.state = TaskState.RUNNING
        self._run()
        self.state = TaskState.FINISHED


class KernelInitTask(Task):
    pass
