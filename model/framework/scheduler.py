"""Select and switch tasks on the calling task's stack."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from greenlet import getcurrent

from framework.contention import CPUSCOPE_CV, TRANSPARENT_CV
from framework.engine import Signal, System, TaskLocalEnv, visibility
from framework.sync_primitives import (
    BusyWaitPreemption,
    GuardBusyWaitPreemption,
    GuardLocalIrq,
    GuardPreemption,
    LocalIrq,
)

if TYPE_CHECKING:
    from kernel.task import Task


@dataclass
class RunQueue(System):
    """The scheduler's task queue and its exclusive mutation boundary."""

    scheduler: Scheduler | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _queue: deque[Task] = field(default_factory=deque, init=False, repr=False)
    selected: Task | None = field(default=None, init=False, repr=False)

    def __iter__(self) -> Iterator[Task]:
        return iter(self._queue)

    def __len__(self) -> int:
        return len(self._queue)

    def __bool__(self) -> bool:
        return bool(self._queue)

    @visibility(TRANSPARENT_CV)
    def _activate_task(self, sig: Signal):
        with GuardBusyWaitPreemption(sig.env.cv, self):
            self.drive(
                sig.env,
                self,
                "_enqueue",
                task=sig.args["task"],
                expected_state=sig.args["expected_state"],
            )

    def _enqueue(self, sig: Signal):
        """Publish a prepared, blocked, or yielding task to the queue."""
        from kernel.task import Task, TaskState

        if self.scheduler is not None:
            self.scheduler._require_current(sig.env)

        task = sig.args["task"]
        assert isinstance(task, Task), "queue entry must be a task"
        if self.scheduler is not None:
            assert task.scheduler is self.scheduler, (
                "task belongs to a different scheduler"
            )
            assert task is not self.scheduler.idle, (
                "idle task cannot be queued as an ordinary task"
            )
        assert task.greenlet is not None, "task has not been set up"
        assert not task.greenlet.dead and task.state is not TaskState.FINISHED, (
            "task has already ended"
        )

        expected_state = sig.args.get("expected_state")
        if expected_state is None:
            assert task.state not in (TaskState.READY, TaskState.RUNNING), (
                "task is already queued or running"
            )
            expected_state = task.state
        operation = {
            TaskState.PREPARED: "_wake_up_new_task",
            TaskState.BLOCKED: "_wake",
            TaskState.RUNNING: "_schedule",
        }.get(expected_state, "queue")
        assert task.state is expected_state, f"task is not ready to {operation}"
        task.state = TaskState.READY
        self._queue.append(task)

    def _select(self, sig: Signal):
        """Select the next ready task, falling back to the idle task."""
        from kernel.task import Task, TaskState

        idle = sig.args["idle"]
        assert isinstance(idle, Task), "scheduler has no idle task"
        task = self._queue.popleft() if self._queue else idle
        assert task.state is TaskState.READY
        assert task.greenlet is not None and not task.greenlet.dead
        task.state = TaskState.RUNNING
        self.selected = task


@dataclass
class Scheduler(System):
    runq: RunQueue = field(default_factory=RunQueue, init=False, repr=False)
    current: Task | None = field(default=None, init=False, repr=False)
    idle: Task | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self.runq.scheduler = self

    def _setup(self, sig: Signal):
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

    @visibility(TRANSPARENT_CV)
    def _get_rq(self, sig: Signal):
        from kernel.task import Task, TaskState

        self._require_current(sig.env)
        task = sig.args["task"]
        assert isinstance(task, Task), "runqueue lookup requires a task"
        assert task.scheduler is self, "task belongs to a different scheduler"
        self.drive(
            sig.env,
            self.runq,
            "_activate_task",
            task=task,
            expected_state=TaskState.PREPARED,
        )

    @visibility(TRANSPARENT_CV)
    def _wake(self, sig: Signal):
        from kernel.task import TaskState

        with GuardLocalIrq(sig.env.cv), GuardBusyWaitPreemption(sig.env.cv, self.runq):
            self.drive(
                sig.env,
                self.runq,
                "_enqueue",
                task=sig.args["task"],
                expected_state=TaskState.BLOCKED,
            )

    @visibility(CPUSCOPE_CV)
    def _switch(self, sig: Signal):
        """Perform one protected scheduling transition."""
        from kernel.task import TaskState

        task = self._require_current(sig.env)
        exiting = sig.args.get("exiting", False)
        blocked = sig.args.get("block", False)
        assert not (exiting and blocked), "exiting task cannot block"
        assert task is not self.idle or not blocked, "idle task cannot block"
        assert task._rq_lock is None, "task already has a pending switch"
        task._rq_lock = BusyWaitPreemption(self.runq)
        task._rq_lock.lock(sig.env.cv)

        if exiting:
            assert task is not self.idle, "idle task cannot exit through the scheduler"
            task.state = TaskState.FINISHED
        elif blocked:
            task.state = TaskState.BLOCKED
        elif task is self.idle:
            task.state = TaskState.READY
        else:
            self.drive(
                sig.env,
                self.runq,
                "_enqueue",
                task=task,
                expected_state=TaskState.RUNNING,
            )

        self.drive(sig.env, self.runq, "_select", idle=self.idle)
        next_task = self.runq.selected
        assert next_task is not None
        self.current = next_task
        assert next_task.greenlet is not None

        if exiting:
            assert task.greenlet is not None
            # Returning makes the source greenlet dead and resumes the target.
            task.greenlet.parent = next_task.greenlet
            return

        if next_task is not task:
            previous = next_task.greenlet.switch(task)
        else:
            previous = task

        # This call returns only when another task has selected its caller again.
        self.drive(sig.env, self, "_finish_switch", previous=previous)

    def _release_switch(self, task: Task) -> None:
        """Balance a task's recorded rq lock and local IRQ protection."""
        assert task._rq_lock is not None, "task has no pending switch"
        task._rq_lock.unlock(task.env.cv)
        LocalIrq().enable(task.env.cv)
        task._rq_lock = None

    @visibility(CPUSCOPE_CV)
    def _finish_switch(self, sig: Signal):
        """Complete a switch on the incoming task's stack."""
        from kernel.task import Task, TaskState

        task = self._require_current(sig.env)
        previous = sig.args["previous"]
        assert isinstance(previous, Task), "switch must identify the previous task"
        assert previous.scheduler is self, "previous task belongs to another scheduler"
        if previous is not task:
            assert previous.state in (
                TaskState.READY,
                TaskState.BLOCKED,
                TaskState.FINISHED,
            ), "previous task is still running"
            if previous.state is TaskState.FINISHED:
                # An exiting task never resumes to balance its saved CV record.
                self._release_switch(previous)
        self._release_switch(task)

    @visibility(TRANSPARENT_CV)
    def _schedule_tail(self, sig: Signal):
        """Establish a new task's inherited protection before its first tail."""
        task = self._require_current(sig.env)
        assert task._rq_lock is None, "new task already has a pending switch"
        with GuardPreemption(sig.env.cv):
            LocalIrq().disable(sig.env.cv)
            # lock() records the inherited rq protection in this task's own CV;
            # the engine does not acquire a second runtime lock.
            task._rq_lock = BusyWaitPreemption(self.runq)
            task._rq_lock.lock(sig.env.cv)
            self.drive(sig.env, self, "_finish_switch", previous=sig.args["previous"])

    def _drive_switch(self, sig: Signal, *, exiting: bool = False) -> None:
        task = self._require_current(sig.env)
        with GuardPreemption(sig.env.cv):
            LocalIrq().disable(sig.env.cv)
            try:
                self.drive(
                    sig.env,
                    self,
                    "_switch",
                    block=sig.args.get("block", False),
                    exiting=exiting,
                )
            except BaseException:
                # Balance only this frame's protection while derivation aborts.
                if task._rq_lock is not None:
                    self._release_switch(task)
                else:
                    LocalIrq().enable(sig.env.cv)
                raise

    @visibility(TRANSPARENT_CV)
    def _schedule(self, sig: Signal):
        self._drive_switch(sig)

    @visibility(TRANSPARENT_CV)
    def _exit(self, sig: Signal):
        """Select the task that receives control when this task returns."""
        self._drive_switch(sig, exiting=True)
