"""Tasks with independent contention state and greenlet call stacks."""

from copy import copy
from enum import Enum, auto

from greenlet import getcurrent, greenlet

from flows.task_flow import TaskFlow
from framework.contention import (
    EXCLUSIVE_CV,
    FREE_CV,
    TASKPRIVATE_CV,
    TRANSPARENT_CV,
    ContentionVector,
)
from framework.engine import Signal, System, TaskLocalEnv, visibility
from framework.scheduler import Scheduler
from framework.sync_primitives import BusyWaitPreemption, GuardBusyWaitIrqSavePreemption


class TaskState(Enum):
    NEW = auto()
    PREPARED = auto()
    READY = auto()
    RUNNING = auto()
    BLOCKED = auto()
    FINISHED = auto()


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
        # Each task keeps its own pending switch protection across suspension.
        self._rq_lock: BusyWaitPreemption | None = None
        self.greenlet: greenlet | None = None
        self.state = TaskState.NEW

    def __repr__(self):
        label = self.name if self.pid is None else f"{self.pid}, {self.name}"
        return f"Task({label})"

    def _scheduler(self) -> Scheduler:
        assert self.scheduler is not None, "task has no initialized scheduler"
        return self.scheduler

    @visibility(TASKPRIVATE_CV)
    def _setup(self, sig: Signal):
        assert self.greenlet is None, "task has already been set up"
        scheduler = self._scheduler()
        scheduler._require_current(sig.env)
        assert self.pid != 0, "task 0 must adopt its existing stack"
        assert scheduler.idle is not None and scheduler.idle.greenlet is not None
        self.greenlet = greenlet(self._run, parent=scheduler.idle.greenlet)
        self.state = TaskState.PREPARED

    @visibility(TRANSPARENT_CV)
    def _wake_up_new_task(self, sig: Signal):
        with GuardBusyWaitIrqSavePreemption(sig.env.cv, self):
            self.drive(
                sig.env,
                self._scheduler(),
                "_get_rq",
                task=self,
            )

    def _run(self, previous: Task) -> Task:
        self.drive(self.env, self._scheduler(), "_schedule_tail", previous=previous)
        # Run the task flow, then return control to the scheduler on exit.
        self.drive(self.env, self.flow, self.action)
        self.drive(self.env, self._scheduler(), "_exit")
        return self


class BootInitTask(Task):
    def __init__(self):
        from flows.boot_init_flow import BootInitFlow

        super().__init__(
            name="boot_init",
            pid=0,
            flow=BootInitFlow(),
            action="_arch_boot",
            cv=EXCLUSIVE_CV,
        )

    def _start(self, sig: Signal):
        assert self.scheduler is None
        assert self.greenlet is None, "task has already been started"

        self.greenlet = getcurrent()
        self.state = TaskState.RUNNING
        self.drive(self.env, self.flow, self.action)
        self.state = TaskState.FINISHED


class KernelInitTask(Task):
    def __init__(self):
        from flows.kernel_init_flow import KernelInitFlow
        from global_vars import gv

        super().__init__(
            name="kernel_init",
            pid=1,
            flow=KernelInitFlow(),
            action="_pre_smp",
            cv=ContentionVector(remote_irq=0, remote_tasks=0),
            scheduler=gv.scheduler,
        )


class KThreaddTask(Task):
    def __init__(self):
        from flows.kthreadd_flow import KthreaddFlow
        from global_vars import gv

        super().__init__(
            name="kthreadd",
            pid=2,
            flow=KthreaddFlow(),
            action="_wait_for_work",
            cv=FREE_CV,
            scheduler=gv.scheduler,
        )
