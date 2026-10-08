"""Exercise saved nested stacks, task isolation and scheduler lifecycles."""

from collections import deque

import pytest
from greenlet import getcurrent, gettrace, greenlet, settrace

from flows.task_flow import TaskFlow
from framework.engine import Signal, System, TaskLocalEnv
from framework.scheduler import RunQueue, Scheduler
from framework.sync import ContentionVector, GuardLocalIrq
from kernel.task import BootInitTask, Task, TaskState

LOCAL_CV = ContentionVector(zero=True, local_irq=1, local_tasks=1)


class EmptyFlow(TaskFlow):
    def start(self, sig: Signal):
        pass


@pytest.fixture
def runtime():
    idle = BootInitTask()
    idle.greenlet = getcurrent()
    idle.state = TaskState.RUNNING
    scheduler = Scheduler()
    System().drive(idle.env, scheduler, "setup")
    return idle, scheduler


def prepare(source: System, env: TaskLocalEnv, task: Task, *, enable: bool = True):
    source.drive(env, task, "setup")
    if enable:
        source.drive(env, task, "enable")


def test_scheduler_uses_a_fullscope_run_queue_boundary():
    scheduler = Scheduler()

    assert isinstance(scheduler.runq, RunQueue)
    for action in ("enqueue", "select"):
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


def test_task_flow_instances_cannot_be_shared(runtime):
    _idle, scheduler = runtime
    flow = EmptyFlow()

    Task("first", flow, "start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="cannot be shared between tasks"):
        Task("second", flow, "start", LOCAL_CV, scheduler)


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

        def start(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            for index in range(self.count):
                assert scheduler.current is task
                assert all(queued is not task for queued in scheduler.runq)
                assert scheduler.idle not in scheduler.runq
                events.append(f"{task.name}{index}")
                self.drive(sig.env, scheduler, "schedule")
            events.append(f"{task.name} end")

    tasks = [
        Task(name, Flow(count), "start", LOCAL_CV, scheduler)
        for name, count in zip("abc", rounds)
    ]
    for task in tasks:
        prepare(source, bootstrap, task)
        assert task.greenlet is not None
        assert task.greenlet.parent is idle.greenlet is getcurrent()
    assert events == []
    assert list(scheduler.runq) == tasks
    source.drive(bootstrap, scheduler, "schedule")
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
    source.drive(bootstrap, scheduler, "schedule")
    assert events == expected


def test_tasks_switch_directly_on_yield_and_exit(runtime):
    idle, scheduler = runtime
    source = System()
    switches: list[tuple[greenlet, greenlet]] = []

    class Flow(TaskFlow):
        def start(self, sig: Signal):
            self.drive(sig.env, scheduler, "schedule")

    first = Task("a", Flow(), "start", LOCAL_CV, scheduler)
    second = Task("b", Flow(), "start", LOCAL_CV, scheduler)
    for task in (first, second):
        prepare(source, idle.env, task)

    def trace(event, pair):
        if event == "switch":
            switches.append(pair)

    previous_trace = gettrace()
    settrace(trace)
    try:
        source.drive(idle.env, scheduler, "schedule")
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
        def start(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            events.append(f"{task.name} start")
            sig.chain(self, "pending", label="outer next")
            self.drive(sig.env, self, "nested", outer=sig)
            events.append(f"{task.name} start resumed")

        def nested(self, sig: Signal):
            env = sig.env
            task = env.task
            assert task is not None
            token = object()
            outer = sig.args["outer"]
            outer.chain(self, "pending", label="outer late")
            sig.chain(self, "pending", label="inner next", token=token)
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
                self.drive(env, scheduler, "schedule")
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

        def pending(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            events.append(f"{task.name} {sig.args['label']}")

        def release(self, env: TaskLocalEnv, action: str):
            if action == "nested":
                assert env.task is not None
                events.append(f"{env.task.name} nested released")

    # Each task owns its own flow even when both use the same flow logic.
    first_flow = Flow()
    second_flow = Flow()
    assert first_flow is not second_flow
    original = ContentionVector(zero=True, local_tasks=1)
    first = Task("a", first_flow, "start", original, scheduler)
    second = Task("b", second_flow, "start", LOCAL_CV, scheduler)
    original.local_irq = 9
    assert first.env.cv.local_irq == 0
    for task in (first, second):
        prepare(source, bootstrap, task)
    source.drive(bootstrap, scheduler, "schedule")

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
    assert lines.count(f"    start -> {flow_repr}") == 2
    assert lines.count(f"        nested -> {flow_repr}") == 2
    assert lines.count("            schedule -> Scheduler()") == 2
    assert lines.count(f"    pending -> {flow_repr}") == 2
    assert lines.count(f"        pending -> {flow_repr}") == 4


def test_task_lifecycle_rejects_invalid_setup_and_enable(runtime):
    idle, scheduler = runtime
    source = System()
    env = idle.env
    task = Task("task", EmptyFlow(), "start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="not been set up"):
        source.drive(env, task, "enable")
    prepare(source, env, task, enable=False)
    with pytest.raises(AssertionError, match="already been set up"):
        source.drive(env, task, "setup")
    source.drive(env, task, "enable")
    with pytest.raises(AssertionError, match="not ready to enable"):
        source.drive(env, task, "enable")
    foreign = Task("foreign", EmptyFlow(), "start", LOCAL_CV, Scheduler())
    with pytest.raises(AssertionError, match="different scheduler"):
        source.drive(env, scheduler, "wake_up_new_task", task=foreign)
    assert list(scheduler.runq) == [task]
    source.drive(env, scheduler, "schedule")
    with pytest.raises(AssertionError, match="already ended"):
        source.drive(env, task, "enable")
    with pytest.raises(AssertionError, match="already been set up"):
        source.drive(env, task, "setup")
    assert env.depth == 0 and env.signal_queues == []


def test_schedule_rejects_bootstrap_foreign_task_and_forged_environments(runtime):
    idle, scheduler = runtime
    source = System()
    bootstrap = idle.env
    other = Task("other", EmptyFlow(), "start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="current task"):
        source.drive(TaskLocalEnv(), scheduler, "schedule")

    class Flow(TaskFlow):
        def start(self, sig: Signal):
            task = sig.env.task
            assert task is not None
            for invalid_env in (TaskLocalEnv(), other.env, TaskLocalEnv(task=task)):
                with pytest.raises(AssertionError, match="current task"):
                    self.drive(invalid_env, scheduler, "schedule")
            with pytest.raises(AssertionError, match="not ready to enable"):
                self.drive(sig.env, task, "enable")
            self.drive(sig.env, scheduler, "schedule")

    task = Task("current", Flow(), "start", LOCAL_CV, scheduler)
    prepare(source, bootstrap, task)
    source.drive(bootstrap, scheduler, "schedule")
    assert task.greenlet is not None and task.greenlet.dead
    assert not scheduler.runq and scheduler.current is idle


@pytest.mark.parametrize("domain", ["remote_irq", "remote_tasks"])
@pytest.mark.parametrize("action", ["enqueue", "schedule"])
def test_management_actions_reject_remote_contention(domain, action):
    scheduler = Scheduler()
    task = Task("task", EmptyFlow(), "start", LOCAL_CV, scheduler)
    cv = ContentionVector(zero=True)
    setattr(cv, domain, 1)
    env = TaskLocalEnv(cv)
    target = scheduler.runq if action == "enqueue" else scheduler
    kwargs = {"task": task} if action == "enqueue" else {}
    with pytest.raises(AssertionError, match=f"violated domains: {domain}"):
        System().drive(env, target, action, **kwargs)
    assert env.depth == 0 and env.signal_queues == []


def test_setup_rejects_an_unrelated_greenlet_context(runtime):
    idle, scheduler = runtime
    task = Task("task", EmptyFlow(), "start", LOCAL_CV, scheduler)
    env = idle.env
    context = greenlet(lambda: System().drive(env, task, "setup"))
    with pytest.raises(AssertionError, match="current task"):
        context.switch()
    assert task.greenlet is None
    assert env.depth == 0 and env.signal_queues == []


def test_task_assertion_propagates_without_cancelling_queued_peers(runtime):
    idle, scheduler = runtime
    source = System()
    events: list[str] = []

    class FailingFlow(TaskFlow):
        def start(self, sig: Signal):
            with GuardLocalIrq(sig.env.cv):
                assert False, "task assertion"

        def release(self, env: TaskLocalEnv, action: str):
            assert env.cv.local_irq == 1
            events.append("release failed action")

    failed = Task("failed", FailingFlow(), "start", LOCAL_CV, scheduler)
    queued = Task("queued", EmptyFlow(), "start", LOCAL_CV, scheduler)
    for task in (failed, queued):
        prepare(source, idle.env, task)
    with pytest.raises(AssertionError, match="task assertion"):
        source.drive(idle.env, scheduler, "schedule")
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
        def start(self, sig: Signal):
            events.append("boot before scheduler")
            assert sig.env.task is boot
            assert boot.greenlet is getcurrent()
            assert boot.scheduler is None and scheduler.idle is None
            self.drive(sig.env, scheduler, "setup")
            assert scheduler.current is scheduler.idle is boot
            worker = Task("worker", EmptyFlow(), "start", LOCAL_CV, scheduler, pid=1)
            prepare(self, sig.env, worker)
            assert worker.greenlet is not None and not worker.greenlet
            sig.chain(self, "continued")
            self.drive(sig.env, scheduler, "schedule")
            assert worker.state is TaskState.FINISHED
            assert scheduler.current is boot and not scheduler.runq
            events.append("boot resumed")

        def continued(self, sig: Signal):
            events.append("boot next signal")

    boot = BootInitTask()
    boot.flow = BootFlow()
    boot.action = "start"
    System().drive(TaskLocalEnv(), boot, "start")
    assert events == ["boot before scheduler", "boot resumed", "boot next signal"]
    assert boot.env.depth == 0 and boot.env.signal_queues == []
    assert scheduler.current is boot
    assert boot.state is TaskState.FINISHED


def test_scheduler_requires_existing_task_zero_and_cannot_be_initialized_twice(runtime):
    idle, initialized = runtime
    source = System()
    scheduler = Scheduler()
    worker = Task("worker", EmptyFlow(), "start", LOCAL_CV, scheduler)
    with pytest.raises(AssertionError, match="not been initialized"):
        source.drive(TaskLocalEnv(), scheduler, "schedule")
    with pytest.raises(AssertionError, match="not been initialized"):
        source.drive(idle.env, worker, "setup")
    with pytest.raises(AssertionError, match="running task 0"):
        source.drive(TaskLocalEnv(), scheduler, "setup")
    with pytest.raises(AssertionError, match="already belongs"):
        source.drive(idle.env, scheduler, "setup")
    with pytest.raises(AssertionError, match="already been initialized"):
        source.drive(idle.env, initialized, "setup")
    unattached = Task("unattached", EmptyFlow(), "start", LOCAL_CV)
    with pytest.raises(AssertionError, match="no initialized scheduler"):
        source.drive(idle.env, unattached, "setup")
    with pytest.raises(AssertionError, match="idle task cannot be queued"):
        source.drive(idle.env, idle, "enable")
    with pytest.raises(AssertionError, match="idle task cannot block"):
        source.drive(idle.env, initialized, "schedule", block=True)
    assert idle.state is TaskState.RUNNING
    assert initialized.current is idle and not initialized.runq


def test_blocked_task_leaves_run_queue_and_resumes_when_woken(runtime):
    idle, scheduler = runtime
    source = System()
    events: list[str] = []

    class Flow(TaskFlow):
        def start(self, sig: Signal):
            token = object()
            sig.chain(self, "pending", token=token)
            with GuardLocalIrq(sig.env.cv):
                events.append("blocked")
                self.drive(sig.env, scheduler, "schedule", block=True)
                assert sig.queue[0].args["token"] is token
                assert sig.env.cv.local_irq == 0
                events.append("resumed")

        def pending(self, sig: Signal):
            events.append("pending")

    task = Task("worker", Flow(), "start", LOCAL_CV, scheduler)
    prepare(source, idle.env, task)
    source.drive(idle.env, scheduler, "schedule")
    assert events == ["blocked"]
    assert task.state is TaskState.BLOCKED
    assert task.greenlet is not None and not task.greenlet.dead
    assert task.env.depth == 3 and len(task.env.signal_queues) == 3
    assert task.env.cv.local_irq == -1
    assert scheduler.current is idle and not scheduler.runq
    source.drive(idle.env, scheduler, "schedule")
    assert events == ["blocked"]
    source.drive(idle.env, scheduler, "wake", task=task)
    assert task.state is TaskState.READY
    assert list(scheduler.runq) == [task]
    source.drive(idle.env, scheduler, "schedule")
    assert events == ["blocked", "resumed", "pending"]
    assert task.state is TaskState.FINISHED and task.greenlet.dead
    assert task.env.depth == 0 and task.env.signal_queues == []
    assert task.env.cv.local_irq == 1
    assert scheduler.current is idle and not scheduler.runq


def test_a_running_task_can_prepare_and_enable_another_task(runtime):
    idle, scheduler = runtime
    events: list[str] = []

    class Flow(TaskFlow):
        def start(self, sig: Signal):
            events.append("parent")
            child = Task("child", Flow(), "child", LOCAL_CV, scheduler)
            prepare(self, sig.env, child)
            self.drive(sig.env, scheduler, "schedule")
            events.append("parent resumed")

        def child(self, sig: Signal):
            events.append("child")

    task = Task("parent", Flow(), "start", LOCAL_CV, scheduler)
    source = System()
    prepare(source, idle.env, task)
    source.drive(idle.env, scheduler, "schedule")
    assert events == ["parent", "child", "parent resumed"]
    assert scheduler.current is idle and not scheduler.runq
