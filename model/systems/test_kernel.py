"""Test boot task initialization, explicit derivation stops and idle scheduling."""

import pytest
from greenlet import getcurrent

from flows.boot_init_flow import BootInitFlow
from flows.kernel_init_flow import KernelInitFlow
from framework.engine import DerivationStopped, Signal, TaskLocalEnv, requires_cv
from framework.scheduler import Scheduler
from global_vars import GlobalVars, gv
from kernel.task import TaskState
from main import main


@pytest.fixture(autouse=True)
def fresh_globals():
    gv.reset()
    yield
    gv.reset()


def test_kernel_setup():
    env = TaskLocalEnv()
    gv.computer.drive(env, gv.kernel, "setup")

    assert gv.kernel_param_table.table == [gv.earlycon_param]
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]
    assert [(item.key, item.val) for item in gv.boot_command_line.items] == [
        ("earlycon", "sbi")
    ]
    assert gv.scheduler is gv.kernel_init_task is gv.kthreadd_task is None


def test_kernel_boot_starts_before_scheduler_and_stops_at_boot_userapp(
    monkeypatch, capsys
):
    env = TaskLocalEnv()
    early_setup = BootInitFlow.early_setup
    setup_scheduler = Scheduler.setup
    schedule = Scheduler.schedule
    events: list[str] = []

    def observe_early(self: BootInitFlow, sig: Signal):
        assert sig.env.task is gv.boot_init_task
        assert gv.boot_init_task.greenlet is getcurrent()
        assert gv.boot_init_task.state is TaskState.RUNNING
        assert gv.scheduler is None and gv.boot_init_task.scheduler is None
        assert gv.kernel_init_task is gv.kthreadd_task is None
        events.append("boot before scheduler")
        early_setup(self, sig)

    def observe_setup(self: Scheduler, sig: Signal):
        assert sig.env.cv.local_irq == 0
        assert gv.kernel_init_task is gv.kthreadd_task is None
        setup_scheduler(self, sig)
        assert self.current is self.idle is gv.boot_init_task
        assert self.context is not None and not self.context
        events.append("scheduler initialized")

    def observe_schedule(self: Scheduler, sig: Signal):
        assert sig.env.task is gv.boot_init_task
        assert [task.pid for task in self.runq] == [1, 2]
        for task in self.runq:
            assert task.state is TaskState.READY
            assert task.greenlet is not None and not task.greenlet
            assert task.greenlet.parent is self.context
        events.append("first yield")
        schedule(self, sig)

    monkeypatch.setattr(BootInitFlow, "early_setup", observe_early)
    monkeypatch.setattr(Scheduler, "setup", observe_setup)
    monkeypatch.setattr(Scheduler, "schedule", observe_schedule)
    gv.computer.drive(env, gv.kernel, "setup")
    with pytest.raises(DerivationStopped, match="^boot_userapp$"):
        gv.computer.drive(env, gv.kernel, "boot")

    assert events == ["boot before scheduler", "scheduler initialized", "first yield"]
    scheduler = gv.scheduler
    assert scheduler is not None
    init = gv.kernel_init_task
    kthreadd = gv.kthreadd_task
    assert init is not None and kthreadd is not None
    assert init.pid == 1 and kthreadd.pid == 2
    assert init.flow is gv.kernel_init_flow
    assert kthreadd.flow is gv.kthreadd_flow
    for task in (gv.boot_init_task, init, kthreadd):
        assert task.scheduler is scheduler
        assert task.state is TaskState.CANCELLED
        assert task.env.depth == 0 and task.env.signal_queues == []
    assert gv.boot_init_task.greenlet is getcurrent()
    assert init.greenlet is not None and init.greenlet.dead
    assert kthreadd.greenlet is not None and kthreadd.greenlet.dead
    assert scheduler.context is not None and scheduler.context.dead
    assert scheduler.current is None and not scheduler.runq
    cv = gv.boot_init_task.env.cv
    assert (cv.local_irq, cv.local_tasks, cv.remote_irq, cv.remote_tasks) == (
        1,
        0,
        0,
        0,
    )
    cv = init.env.cv
    assert (cv.local_irq, cv.local_tasks, cv.remote_irq, cv.remote_tasks) == (
        1,
        1,
        0,
        0,
    )
    assert env.task is None
    assert env.cv <= TaskLocalEnv().cv
    assert env.depth == 0 and env.signal_queues == []
    output = capsys.readouterr().out
    steps = (
        "arch_boot -> BootInitFlow()",
        "sched_init -> BootInitFlow()",
        "setup -> Scheduler()",
        "enable_irq -> BootInitFlow()",
        "setup -> Task(1, kernel_init)",
        "enable -> Task(1, kernel_init)",
        "setup -> Task(2, kthreadd)",
        "enable -> Task(2, kthreadd)",
        "schedule -> Scheduler()",
        "pre_smp -> KernelInitFlow()",
        "bringup_nonboot_cpus -> KernelInitFlow()",
        "final_init -> KernelInitFlow()",
        "boot_userapp -> KernelInitFlow()",
    )
    offsets = [output.index(step) for step in steps]
    assert offsets == sorted(offsets)
    assert "enter_idle ->" not in output
    assert "wait_for_work ->" not in output
    assert gv.early_console_dev.console.ready


def test_idle_keeps_scheduling_and_wakes_blocked_init_while_kthreadd_waits(monkeypatch):
    events: list[str] = []

    class WaitingInitFlow(KernelInitFlow):
        def pre_smp(self, sig: Signal):
            assert sig.env.task is not None
            scheduler = sig.env.task.require_scheduler()
            events.append("init running")
            while True:
                self.drive(sig.env, scheduler, "schedule", block=True)
                events.append("init resumed")

    gv.kernel_init_flow = WaitingInitFlow()
    idle_action = BootInitFlow.do_idle
    iterations = 0

    @requires_cv(gv.boot_init_flow.resolve_require_cv("do_idle"))
    def observe_idle(self: BootInitFlow, sig: Signal):
        nonlocal iterations
        iterations += 1
        scheduler = gv.scheduler
        init = gv.kernel_init_task
        kthreadd = gv.kthreadd_task
        assert scheduler is not None and init is not None and kthreadd is not None
        assert scheduler.current is scheduler.idle is gv.boot_init_task
        assert not scheduler.runq
        assert init.state is kthreadd.state is TaskState.BLOCKED
        assert kthreadd.greenlet is not None and not kthreadd.greenlet.dead
        assert kthreadd.env.depth == 2 and len(kthreadd.env.signal_queues) == 2
        assert sig.env.cv.local_tasks == 0
        events.append("idle")
        if iterations == 3:
            raise DerivationStopped("idle test boundary")
        self.drive(sig.env, init, "enable")
        idle_action(self, sig)

    monkeypatch.setattr(BootInitFlow, "do_idle", observe_idle)
    env = TaskLocalEnv()
    gv.computer.drive(env, gv.kernel, "setup")
    with pytest.raises(DerivationStopped, match="idle test boundary"):
        gv.computer.drive(env, gv.kernel, "boot")

    assert events == [
        "init running",
        "idle",
        "init resumed",
        "idle",
        "init resumed",
        "idle",
    ]
    assert gv.scheduler is not None
    assert gv.scheduler.context is not None and gv.scheduler.context.dead
    for task in (gv.boot_init_task, gv.kernel_init_task, gv.kthreadd_task):
        assert task is not None
        assert task.state is TaskState.CANCELLED
        assert task.env.depth == 0 and task.env.signal_queues == []


def test_main_reports_explicit_boundary(capsys):
    main()
    assert capsys.readouterr().out.endswith("Derivation stopped at boot_userapp.\n")


def test_main_does_not_hide_unrelated_assertions(monkeypatch):
    error = AssertionError("unexpected failure")

    def fail(self: KernelInitFlow, sig: Signal):
        raise error

    monkeypatch.setattr(KernelInitFlow, "boot_userapp", fail)
    with pytest.raises(AssertionError) as exc_info:
        main()
    assert exc_info.value is error
    assert gv.scheduler is not None and gv.scheduler.current is None


def test_boot_error_before_scheduler_initialization_propagates(monkeypatch):
    error = RuntimeError("early setup failed")

    def fail(self: BootInitFlow, sig: Signal):
        raise error

    monkeypatch.setattr(BootInitFlow, "early_setup", fail)
    with pytest.raises(RuntimeError) as exc_info:
        gv.computer.drive(TaskLocalEnv(), gv.kernel, "boot")
    assert exc_info.value is error
    assert gv.scheduler is None
    assert gv.boot_init_task.state is TaskState.CANCELLED
    assert gv.boot_init_task.env.depth == 0
    assert gv.boot_init_task.env.signal_queues == []


def test_global_objects_create_only_task_zero_before_boot_and_reset_after_stop():
    first = GlobalVars()
    second = GlobalVars()
    first.boot_init_task.env.cv.local_irq = 7
    first.kernel_init_flow.visibility.local_irq = 0
    for objects in (first, second):
        assert objects.boot_init_task.flow is objects.boot_init_flow
        assert objects.boot_init_task.pid == 0
        assert objects.boot_init_task.env.task is objects.boot_init_task
        assert objects.boot_init_task.scheduler is None
        assert objects.boot_init_task.greenlet is None
        assert (
            objects.scheduler
            is objects.kernel_init_task
            is objects.kthreadd_task
            is None
        )
    assert second.boot_init_task.env.cv.local_irq == 0
    assert second.kernel_init_flow.visibility.local_irq == 1
    main()
    old_task = gv.boot_init_task
    old_scheduler = gv.scheduler
    old_init = gv.kernel_init_task
    old_kthreadd = gv.kthreadd_task
    gv.reset()
    assert gv.boot_init_task is not old_task
    assert gv.scheduler is gv.kernel_init_task is gv.kthreadd_task is None
    assert gv.boot_init_task.env.cv.local_irq == 0
    main()
    assert gv.scheduler is not old_scheduler
    assert gv.kernel_init_task is not old_init
    assert gv.kthreadd_task is not old_kthreadd
