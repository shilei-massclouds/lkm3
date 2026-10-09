"""Exercise saved nested stacks, task isolation and scheduler lifecycles."""

from collections import deque

import pytest
from greenlet import getcurrent, gettrace, greenlet, settrace

from flows.task_flow import TaskFlow
from framework.contention import CPUSCOPE_CV, ContentionVector
from framework.engine import Signal, System, TaskLocalEnv, visibility
from framework.scheduler import RunQueue, Scheduler
from framework.sync_primitives import (
    BusyWaitPreemption,
    GuardBusyWaitIrqSavePreemption,
    GuardLocalIrq,
    LocalIrq,
)
from kernel.task import BootInitTask, Task, TaskState

LOCAL_CV = ContentionVector(zero=True, local_irq=1, local_tasks=1)


class EmptyFlow(TaskFlow):
    def _start(self, sig: Signal):
        pass


@pytest.fixture
def runtime():
    idle = BootInitTask()
    idle.greenlet = getcurrent()
    idle.state = TaskState.RUNNING
    scheduler = Scheduler()
    System().drive(idle.env, scheduler, "_setup")
    return idle, scheduler


def prepare(source: System, env: TaskLocalEnv, task: Task, *, wake: bool = True):
    source.drive(env, task, "_setup")
    if wake:
        source.drive(env, task, "_wake_up_new_task")


def test_scheduler_uses_a_fullscope_run_queue_boundary():
    scheduler = Scheduler()

    assert isinstance(scheduler.runq, RunQueue)
    for action in ("_enqueue", "_select"):
        visible = scheduler.runq.resolve_visibility(action)
        assert all(
            getattr(visible, domain) == 1
            for domain in (
                "local_irq",
                "local_tasks",
                "remote_irq",
                "remote_tasks",
            )
        )


def test_task_lock_does_not_authorize_runqueue_mutation(runtime):
    idle, scheduler = runtime
    source = System()
    idle.env.cv = ContentionVector.ones()
    task = Task("new", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    prepare(source, idle.env, task, wake=False)

    with GuardBusyWaitIrqSavePreemption(idle.env.cv, task):
        with pytest.raises(
            AssertionError, match="violated domains: remote_irq, remote_tasks"
        ):
            source.drive(
                idle.env,
                scheduler.runq,
                "_enqueue",
                task=task,
                expected_state=TaskState.PREPARED,
            )
        assert task.state is TaskState.PREPARED
        assert not scheduler.runq

    source.drive(idle.env, task, "_wake_up_new_task")
    assert task.state is TaskState.READY
    assert list(scheduler.runq) == [task]
    assert all(not stack for stack in idle.env.cv.stacks.values())


def test_new_task_activation_records_both_protected_targets(runtime, monkeypatch):
    idle, scheduler = runtime
    idle.env.cv = ContentionVector.ones()
    task = Task("new", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    enqueue = RunQueue._enqueue

    def _observe_enqueue(self: RunQueue, sig: Signal):
        assert sig.env.cv.stacks["local_irq"] == [None]
        assert sig.env.cv.stacks["local_tasks"] == [None, None]
        assert sig.env.cv.stacks["remote_irq"][0] is task
        assert sig.env.cv.stacks["remote_irq"][1] is self
        assert sig.env.cv.stacks["remote_tasks"][0] is task
        assert sig.env.cv.stacks["remote_tasks"][1] is self
        enqueue(self, sig)

    monkeypatch.setattr(RunQueue, "_enqueue", _observe_enqueue)
    prepare(System(), idle.env, task)
    assert list(scheduler.runq) == [task]
    assert all(not stack for stack in idle.env.cv.stacks.values())


def test_task_flow_instances_cannot_be_shared(runtime):
    _idle, scheduler = runtime
    flow = EmptyFlow()

    Task("first", flow, "_start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="cannot be shared between tasks"):
        Task("second", flow, "_start", LOCAL_CV, scheduler)


@pytest.mark.parametrize(
    "rounds, expected",
    [
        (
            (2, 2, 2),
            ["a0", "b0", "c0", "a1", "b1", "c1", "a end", "b end", "c end"],
        ),
        ((1, 0, 2), ["a0", "b end", "c0", "a end", "c1", "c end"]),
        ((2,), ["a0", "a1", "a end"]),
    ],
)
def test_round_robin_self_yield_and_finished_tasks(runtime, rounds, expected):
    idle, scheduler = runtime
    source = System()
    bootstrap = idle.env
    events: list[str] = []

    class Flow(TaskFlow):
        def __init__(self, count: int):
            super().__init__()
            self.count = count

        def _start(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            for index in range(self.count):
                assert scheduler.current is task
                assert all(queued is not task for queued in scheduler.runq)
                assert scheduler.idle not in scheduler.runq
                events.append(f"{task.name}{index}")
                self.drive(sig.env, scheduler, "_schedule")
            events.append(f"{task.name} end")

    tasks = [
        Task(name, Flow(count), "_start", LOCAL_CV, scheduler)
        for name, count in zip("abc", rounds)
    ]
    for task in tasks:
        prepare(source, bootstrap, task)
        assert task.greenlet is not None
        assert task.greenlet.parent is idle.greenlet is getcurrent()
    assert events == []
    assert list(scheduler.runq) == tasks
    source.drive(bootstrap, scheduler, "_schedule")
    assert events == expected
    for task in tasks:
        assert task.greenlet is not None and task.greenlet.dead
        assert task.env.depth == 0 and task.env.signal_queues == []
    assert bootstrap.depth == 0 and bootstrap.signal_queues == []
    assert not scheduler.runq and scheduler.current is idle
    assert idle.state is TaskState.RUNNING
    assert not hasattr(scheduler, "run")
    assert not hasattr(scheduler, "context")
    assert not hasattr(scheduler, "_dispatch")
    source.drive(bootstrap, scheduler, "_schedule")
    assert events == expected


def test_tasks_switch_directly_on_yield_and_exit(runtime):
    idle, scheduler = runtime
    source = System()
    switches: list[tuple[greenlet, greenlet]] = []

    class Flow(TaskFlow):
        def _start(self, sig: Signal):
            self.drive(sig.env, scheduler, "_schedule")

    first = Task("a", Flow(), "_start", LOCAL_CV, scheduler)
    second = Task("b", Flow(), "_start", LOCAL_CV, scheduler)
    for task in (first, second):
        prepare(source, idle.env, task)

    def trace(event, pair):
        if event == "switch":
            switches.append(pair)

    previous_trace = gettrace()
    settrace(trace)
    try:
        source.drive(idle.env, scheduler, "_schedule")
    finally:
        settrace(previous_trace)

    assert switches == [
        (idle.greenlet, first.greenlet),
        (first.greenlet, second.greenlet),
        (second.greenlet, first.greenlet),
        (first.greenlet, second.greenlet),
        (second.greenlet, idle.greenlet),
    ]


def test_nested_yields_preserve_locals_environments_queues_and_release_timing(
    runtime, capsys
):
    idle, scheduler = runtime
    source = System()
    bootstrap = idle.env
    events: list[str] = []
    suspended: dict[str, tuple[TaskLocalEnv, tuple[deque[Signal], ...]]] = {}

    class Flow(TaskFlow):
        def _start(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            events.append(f"{task.name} start")
            sig.chain(self, "_pending", label="outer next")
            self.drive(sig.env, self, "_nested", outer=sig)
            events.append(f"{task.name} start resumed")

        def _nested(self, sig: Signal):
            env = sig.env
            task = env.task
            assert task is not None
            token = object()
            outer = sig.args["outer"]
            outer.chain(self, "_pending", label="outer late")
            sig.chain(self, "_pending", label="inner next", token=token)
            queues = tuple(env.signal_queues)
            assert env.depth == 2 and len(queues) == 2
            suspended[task.name] = (env, queues)
            with GuardLocalIrq(env.cv):
                irq = env.cv.local_irq
                assert idle.env.depth == 2 and len(idle.env.signal_queues) == 2
                assert idle.env.cv.local_irq == -1
                if task.name == "b":
                    other_env, other_queues = suspended["a"]
                    assert other_env is not env and other_env.cv is not env.cv
                    assert other_env.depth == 4
                    assert other_env.cv.local_irq == -2
                    assert len(other_env.signal_queues) == 4
                    assert all(
                        actual is saved
                        for actual, saved in zip(other_env.signal_queues, other_queues)
                    )
                    assert not any("released" in event for event in events)
                events.append(f"{task.name} yielding")
                self.drive(env, scheduler, "_schedule")
                assert sig.env is env is task.env
                assert env.depth == 2
                assert len(env.signal_queues) == len(queues)
                assert all(
                    actual is saved for actual, saved in zip(env.signal_queues, queues)
                )
                assert env.cv.local_irq == irq
                assert sig.queue[0].args["token"] is token
                assert outer.queue is queues[0]
                events.append(f"{task.name} nested resumed")

        def _pending(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            events.append(f"{task.name} {sig.args['label']}")

        def release(self, env: TaskLocalEnv, action: str):
            if action == "_nested":
                assert env.task is not None
                events.append(f"{env.task.name} nested released")

    # Each task owns its own flow even when both use the same flow logic.
    first_flow = Flow()
    second_flow = Flow()
    assert first_flow is not second_flow
    original = ContentionVector(zero=True, local_tasks=1)
    first = Task("a", first_flow, "_start", original, scheduler)
    second = Task("b", second_flow, "_start", LOCAL_CV, scheduler)
    original.local_irq = 9
    assert first.env.cv.local_irq == 0
    for task in (first, second):
        prepare(source, bootstrap, task)
    source.drive(bootstrap, scheduler, "_schedule")

    assert events == [
        "a start",
        "a yielding",
        "b start",
        "b yielding",
        "a nested resumed",
        "a nested released",
        "a inner next",
        "a start resumed",
        "a outer next",
        "a outer late",
        "b nested resumed",
        "b nested released",
        "b inner next",
        "b start resumed",
        "b outer next",
        "b outer late",
    ]
    assert first.env.cv.local_irq == 0 and second.env.cv.local_irq == 1
    assert first.env.depth == second.env.depth == 0
    assert first.env.signal_queues == second.env.signal_queues == []
    lines = capsys.readouterr().out.splitlines()
    flow_repr = repr(first_flow)
    assert lines.count(f"    _start -> {flow_repr}") == 2
    assert lines.count(f"        _nested -> {flow_repr}") == 2
    assert lines.count("            _schedule -> Scheduler()") == 2
    assert lines.count(f"    _pending -> {flow_repr}") == 2
    assert lines.count(f"        _pending -> {flow_repr}") == 4


def test_task_lifecycle_rejects_invalid_setup_and_wake(runtime):
    idle, scheduler = runtime
    source = System()
    env = idle.env
    task = Task("task", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="not been set up"):
        source.drive(env, task, "_wake_up_new_task")
    prepare(source, env, task, wake=False)
    with pytest.raises(AssertionError, match="already been set up"):
        source.drive(env, task, "_setup")
    source.drive(env, task, "_wake_up_new_task")
    with pytest.raises(AssertionError, match="not ready to _wake_up_new_task"):
        source.drive(env, task, "_wake_up_new_task")
    foreign = Task("foreign", EmptyFlow(), "_start", LOCAL_CV, Scheduler())
    with pytest.raises(AssertionError, match="different scheduler"):
        source.drive(env, scheduler, "_get_rq", task=foreign)
    assert list(scheduler.runq) == [task]
    source.drive(env, scheduler, "_schedule")
    with pytest.raises(AssertionError, match="already ended"):
        source.drive(env, task, "_wake_up_new_task")
    with pytest.raises(AssertionError, match="already been set up"):
        source.drive(env, task, "_setup")
    assert env.depth == 0 and env.signal_queues == []


def test_schedule_rejects_bootstrap_foreign_task_and_forged_environments(runtime):
    idle, scheduler = runtime
    source = System()
    bootstrap = idle.env
    other = Task("other", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="current task"):
        source.drive(TaskLocalEnv(), scheduler, "_schedule")

    class Flow(TaskFlow):
        def _start(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            for invalid_env in (TaskLocalEnv(), other.env, TaskLocalEnv(task=task)):
                with pytest.raises(AssertionError, match="current task"):
                    self.drive(invalid_env, scheduler, "_schedule")
            with pytest.raises(AssertionError, match="not ready to _wake_up_new_task"):
                self.drive(sig.env, task, "_wake_up_new_task")
            self.drive(sig.env, scheduler, "_schedule")

    task = Task("current", Flow(), "_start", LOCAL_CV, scheduler)
    prepare(source, bootstrap, task)
    source.drive(bootstrap, scheduler, "_schedule")
    assert task.greenlet is not None and task.greenlet.dead
    assert not scheduler.runq and scheduler.current is idle


@pytest.mark.parametrize("domain", ["remote_irq", "remote_tasks"])
def test_runqueue_enqueue_rejects_remote_contention(domain):
    scheduler = Scheduler()
    task = Task("task", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    cv = ContentionVector(zero=True)
    cv.expose(domain)
    env = TaskLocalEnv(cv)
    with pytest.raises(AssertionError, match=f"violated domains: {domain}"):
        System().drive(env, scheduler.runq, "_enqueue", task=task)
    assert env.depth == 0 and env.signal_queues == []


@pytest.mark.parametrize("domain", ["remote_irq", "remote_tasks"])
def test_schedule_protects_runqueue_against_remote_contention(
    runtime, domain, monkeypatch
):
    idle, scheduler = runtime
    env = idle.env
    env.cv.expose(domain)
    initial_stacks = {name: list(stack) for name, stack in env.cv.stacks.items()}
    select = RunQueue._select
    selections: list[RunQueue] = []

    def _observe_select(self: RunQueue, sig: Signal):
        assert getattr(sig.env.cv, domain) == 0
        assert sig.env.cv.stacks[domain][-1] is self
        selections.append(self)
        select(self, sig)

    monkeypatch.setattr(RunQueue, "_select", _observe_select)

    assert scheduler.check_invariant(env, "_switch")
    System().drive(env, scheduler, "_schedule")

    assert selections == [scheduler.runq]
    assert scheduler.runq.selected is idle and not scheduler.runq
    assert env.cv.local_irq == env.cv.local_tasks == 0
    assert getattr(env.cv, domain) == 1
    assert env.cv.stacks == initial_stacks
    assert env.depth == 0 and env.signal_queues == []


def test_switch_tails_balance_first_entry_resume_and_exit(runtime, monkeypatch):
    idle, scheduler = runtime
    idle.env.cv = ContentionVector.ones()
    source = System()
    transitions: list[tuple[str, str]] = []
    finish_switch = Scheduler._finish_switch
    lock = BusyWaitPreemption.lock
    unlock = BusyWaitPreemption.unlock
    enable_irq = LocalIrq.enable

    def observe_lock(self: BusyWaitPreemption, cv: ContentionVector):
        assert cv.local_irq == 0
        lock(self, cv)

    def observe_unlock(self: BusyWaitPreemption, cv: ContentionVector):
        assert cv.local_irq == 0
        unlock(self, cv)

    def observe_enable_irq(self: LocalIrq, cv: ContentionVector):
        assert cv.local_irq == 0
        assert cv.stacks["remote_irq"] == cv.stacks["remote_tasks"] == []
        enable_irq(self, cv)

    @visibility(CPUSCOPE_CV)
    def _observe_finish(self: Scheduler, sig: Signal):
        task = sig.env.task
        previous = sig.args["previous"]
        assert task is not None and task.greenlet is getcurrent()
        assert sig.env.cv.local_irq == 0
        assert sig.env.cv.local_tasks == -1
        assert sig.env.cv.remote_irq == sig.env.cv.remote_tasks == 0
        assert sig.env.cv.stacks["remote_irq"] == [self.runq]
        assert sig.env.cv.stacks["remote_tasks"] == [self.runq]
        assert task._rq_lock is not None
        assert previous._rq_lock is not None
        transitions.append((previous.name, task.name))
        finish_switch(self, sig)
        assert task._rq_lock is None
        assert sig.env.cv.local_irq == 1
        assert sig.env.cv.local_tasks == 0
        assert sig.env.cv.remote_irq == sig.env.cv.remote_tasks == 1
        assert sig.env.cv.stacks["remote_irq"] == []
        assert sig.env.cv.stacks["remote_tasks"] == []
        if previous.state is TaskState.FINISHED:
            assert previous.greenlet is not None and previous.greenlet.dead
            assert previous._rq_lock is None
            assert all(not stack for stack in previous.env.cv.stacks.values())

    class Flow(TaskFlow):
        def _start(self, sig: Signal):
            assert all(not stack for stack in sig.env.cv.stacks.values())
            self.drive(sig.env, scheduler, "_schedule")
            assert all(not stack for stack in sig.env.cv.stacks.values())

    monkeypatch.setattr(Scheduler, "_finish_switch", _observe_finish)
    monkeypatch.setattr(BusyWaitPreemption, "lock", observe_lock)
    monkeypatch.setattr(BusyWaitPreemption, "unlock", observe_unlock)
    monkeypatch.setattr(LocalIrq, "enable", observe_enable_irq)
    tasks = [
        Task("a", Flow(), "_start", ContentionVector.ones(), scheduler),
        Task("b", EmptyFlow(), "_start", ContentionVector.ones(), scheduler),
        Task("c", EmptyFlow(), "_start", ContentionVector.ones(), scheduler),
    ]
    for task in tasks:
        prepare(source, idle.env, task)
    source.drive(idle.env, scheduler, "_schedule")

    assert transitions == [
        ("boot_init", "a"),
        ("a", "b"),
        ("b", "c"),
        ("c", "a"),
        ("a", "boot_init"),
    ]
    for task in (idle, *tasks):
        assert task._rq_lock is None
        assert all(not stack for stack in task.env.cv.stacks.values())
        assert task.env.cv.local_irq == task.env.cv.local_tasks == 1
        assert task.env.cv.remote_irq == task.env.cv.remote_tasks == 1
    assert scheduler.current is idle and not scheduler.runq


@pytest.mark.parametrize("domain", ["local_irq", "local_tasks"])
def test_switch_still_requires_local_protection(runtime, domain):
    idle, scheduler = runtime
    idle.env.cv.expose(domain)

    with pytest.raises(AssertionError, match=f"violated domains: {domain}"):
        System().drive(idle.env, scheduler, "_switch")

    assert idle.state is TaskState.RUNNING
    assert scheduler.current is idle and not scheduler.runq
    assert idle.env.depth == 0 and idle.env.signal_queues == []


def test_setup_rejects_an_unrelated_greenlet_context(runtime):
    idle, scheduler = runtime
    task = Task("task", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    env = idle.env
    context = greenlet(lambda: System().drive(env, task, "_setup"))
    with pytest.raises(AssertionError, match="current task"):
        context.switch()
    assert task.greenlet is None
    assert env.depth == 0 and env.signal_queues == []


def test_task_assertion_propagates_without_cancelling_queued_peers(runtime):
    idle, scheduler = runtime
    source = System()
    events: list[str] = []

    class FailingFlow(TaskFlow):
        def _start(self, sig: Signal):
            with GuardLocalIrq(sig.env.cv):
                assert False, "task assertion"

        def release(self, env: TaskLocalEnv, action: str):
            assert env.cv.local_irq == 1
            events.append("release failed action")

    failed = Task("failed", FailingFlow(), "_start", LOCAL_CV, scheduler)
    queued = Task("queued", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    for task in (failed, queued):
        prepare(source, idle.env, task)
    with pytest.raises(AssertionError, match="task assertion"):
        source.drive(idle.env, scheduler, "_schedule")
    assert events == ["release failed action"]
    assert failed.greenlet is not None and failed.greenlet.dead
    assert failed.env.depth == 0 and failed.env.signal_queues == []
    assert idle.env.depth == 0 and idle.env.signal_queues == []
    assert queued.greenlet is not None and not queued.greenlet
    assert queued.state is TaskState.READY
    assert list(scheduler.runq) == [queued]


def test_task_zero_starts_directly_and_initializes_scheduler_during_its_flow():
    events: list[str] = []
    scheduler = Scheduler()

    class BootFlow(TaskFlow):
        def _start(self, sig: Signal):
            events.append("boot before scheduler")
            assert sig.env.task is boot
            assert boot.greenlet is getcurrent()
            assert boot.scheduler is None and scheduler.idle is None
            self.drive(sig.env, scheduler, "_setup")
            assert scheduler.current is scheduler.idle is boot
            worker = Task("worker", EmptyFlow(), "_start", LOCAL_CV, scheduler, pid=1)
            prepare(self, sig.env, worker)
            assert worker.greenlet is not None and not worker.greenlet
            sig.chain(self, "_continued")
            self.drive(sig.env, scheduler, "_schedule")
            assert worker.state is TaskState.FINISHED
            assert scheduler.current is boot and not scheduler.runq
            events.append("boot resumed")

        def _continued(self, sig: Signal):
            events.append("boot next signal")

    boot = BootInitTask()
    boot.flow = BootFlow()
    boot.action = "_start"
    System().drive(TaskLocalEnv(), boot, "_start")
    assert events == ["boot before scheduler", "boot resumed", "boot next signal"]
    assert boot.env.depth == 0 and boot.env.signal_queues == []
    assert scheduler.current is boot
    assert boot.state is TaskState.FINISHED


def test_scheduler_requires_existing_task_zero_and_cannot_be_initialized_twice(runtime):
    idle, initialized = runtime
    source = System()
    scheduler = Scheduler()
    worker = Task("worker", EmptyFlow(), "_start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="not been initialized"):
        source.drive(TaskLocalEnv(), scheduler, "_schedule")
    with pytest.raises(AssertionError, match="not been initialized"):
        source.drive(idle.env, worker, "_setup")
    with pytest.raises(AssertionError, match="running task 0"):
        source.drive(TaskLocalEnv(), scheduler, "_setup")
    with pytest.raises(AssertionError, match="already belongs"):
        source.drive(idle.env, scheduler, "_setup")
    with pytest.raises(AssertionError, match="already been initialized"):
        source.drive(idle.env, initialized, "_setup")
    unattached = Task("unattached", EmptyFlow(), "_start", LOCAL_CV)
    with pytest.raises(AssertionError, match="no initialized scheduler"):
        source.drive(idle.env, unattached, "_setup")
    with pytest.raises(AssertionError, match="idle task cannot be queued"):
        source.drive(idle.env, idle, "_wake_up_new_task")
    with pytest.raises(AssertionError, match="idle task cannot block"):
        source.drive(idle.env, initialized, "_schedule", block=True)
    assert idle.state is TaskState.RUNNING
    assert initialized.current is idle and not initialized.runq


@pytest.mark.parametrize("remote_contention", [False, True])
def test_blocked_task_leaves_run_queue_and_resumes_when_woken(
    runtime, remote_contention
):
    idle, scheduler = runtime
    source = System()
    events: list[str] = []

    class Flow(TaskFlow):
        def _start(self, sig: Signal):
            token = object()
            sig.chain(self, "_pending", token=token)
            with GuardLocalIrq(sig.env.cv):
                events.append("blocked")
                self.drive(sig.env, scheduler, "_schedule", block=True)
                assert sig.queue[0].args["token"] is token
                assert sig.env.cv.local_irq == 0
                events.append("resumed")

        def _pending(self, sig: Signal):
            events.append("pending")

    if remote_contention:
        idle.env.cv.expose("remote_irq", "remote_tasks")
    cv = ContentionVector.ones() if remote_contention else LOCAL_CV
    task = Task("worker", Flow(), "_start", cv, scheduler)
    prepare(source, idle.env, task)
    source.drive(idle.env, scheduler, "_schedule")
    assert events == ["blocked"]
    assert task.state is TaskState.BLOCKED
    assert task.greenlet is not None and not task.greenlet.dead
    assert task.env.depth == 3 and len(task.env.signal_queues) == 3
    assert task.env.cv.local_irq == -1
    assert scheduler.current is idle and not scheduler.runq
    source.drive(idle.env, scheduler, "_schedule")
    assert events == ["blocked"]
    source.drive(idle.env, scheduler, "_wake", task=task)
    assert task.state is TaskState.READY
    assert list(scheduler.runq) == [task]
    source.drive(idle.env, scheduler, "_schedule")
    assert events == ["blocked", "resumed", "pending"]
    assert task.state is TaskState.FINISHED and task.greenlet.dead
    assert task.env.depth == 0 and task.env.signal_queues == []
    assert task.env.cv.local_irq == 1
    assert task.env.cv.remote_irq == task.env.cv.remote_tasks == int(remote_contention)
    assert task._rq_lock is None
    assert scheduler.current is idle and not scheduler.runq


def test_a_running_task_can_prepare_and_enable_another_task(runtime):
    idle, scheduler = runtime
    events: list[str] = []

    class Flow(TaskFlow):
        def _start(self, sig: Signal):
            events.append("parent")
            child = Task("child", Flow(), "_child", LOCAL_CV, scheduler)
            prepare(self, sig.env, child)
            self.drive(sig.env, scheduler, "_schedule")
            events.append("parent resumed")

        def _child(self, sig: Signal):
            events.append("child")

    task = Task("parent", Flow(), "_start", LOCAL_CV, scheduler)
    source = System()
    prepare(source, idle.env, task)
    source.drive(idle.env, scheduler, "_schedule")
    assert events == ["parent", "child", "parent resumed"]
    assert scheduler.current is idle and not scheduler.runq
