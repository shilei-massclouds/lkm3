"""Test boot task initialization, assertion boundaries and idle scheduling."""

import pytest
from greenlet import getcurrent

from flows.boot_init_flow import BootInitFlow
from flows.kernel_init_flow import KernelInitFlow
from framework.engine import Signal, TaskLocalEnv, requires_cv
from framework.scheduler import Scheduler
from global_vars import GlobalVars, gv
from kernel.task import BootInitTask, TaskState
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


def test_kernel_boot_starts_before_scheduler_and_terminates_at_boot_userapp(
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
        assert not hasattr(self, "context")
        events.append("scheduler initialized")

    def observe_schedule(self: Scheduler, sig: Signal):
        assert sig.env.task is gv.boot_init_task
        assert [task.pid for task in self.runq] == [1, 2]
        for task in self.runq:
            assert task.state is TaskState.READY
            assert task.greenlet is not None and not task.greenlet
            assert task.greenlet.parent is gv.boot_init_task.greenlet
        events.append("first yield")
        schedule(self, sig)

    monkeypatch.setattr(BootInitFlow, "early_setup", observe_early)
    monkeypatch.setattr(Scheduler, "setup", observe_setup)
    monkeypatch.setattr(Scheduler, "schedule", observe_schedule)
    gv.computer.drive(env, gv.kernel, "setup")
    with pytest.raises(SystemExit) as exc_info:
        gv.computer.drive(env, gv.kernel, "boot")
    assert exc_info.value.code == 0

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
        assert task.env.depth == 0 and task.env.signal_queues == []
    assert gv.boot_init_task.greenlet is getcurrent()
    assert init.greenlet is not None and init.greenlet.dead
    assert kthreadd.greenlet is not None and not kthreadd.greenlet
    assert scheduler.current is init
    assert list(scheduler.runq) == [kthreadd]
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
    assert "[Reach UserApp]" in output
    assert gv.early_console_dev.console.ready


def test_finite_idle_keeps_scheduling_and_wakes_blocked_init_while_kthreadd_waits(
    monkeypatch,
):
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

    @requires_cv(gv.boot_init_task.flow.resolve_require_cv("do_idle"))
    def observe_idle(self: BootInitFlow, sig: Signal):
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
        self.drive(sig.env, init, "enable")
        idle_action(self, sig)

    monkeypatch.setattr(BootInitFlow, "do_idle", observe_idle)
    env = TaskLocalEnv()
    gv.computer.drive(env, gv.kernel, "setup")
    gv.computer.drive(env, gv.kernel, "boot")

    assert events == [
        "init running",
        "idle",
        "init resumed",
        "idle",
        "init resumed",
        "idle",
        "init resumed",
    ]
    assert gv.scheduler is not None
    assert gv.scheduler.current is gv.boot_init_task and not gv.scheduler.runq
    assert gv.boot_init_task.state is TaskState.FINISHED
    assert (
        gv.boot_init_task.env.depth == 0 and gv.boot_init_task.env.signal_queues == []
    )
    for task in (gv.kernel_init_task, gv.kthreadd_task):
        assert task is not None
        assert task.state is TaskState.BLOCKED
        assert task.greenlet is not None and not task.greenlet.dead
        assert task.env.depth == 2 and len(task.env.signal_queues) == 2


def test_main_propagates_boundary_termination(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert "[Reach UserApp]" in capsys.readouterr().out


def test_main_uses_independent_setup_and_boot_environments(monkeypatch):
    calls = []

    def observe_drive(env, target, action):
        calls.append((env, target, action))

    monkeypatch.setattr(gv.computer, "drive", observe_drive)
    main()

    assert [action for _, _, action in calls] == ["setup", "boot"]
    assert calls[0][0] is not calls[1][0]
    assert all(env.task is None for env, _, _ in calls)


def test_main_does_not_hide_unrelated_assertions(monkeypatch):
    def fail(self: KernelInitFlow, sig: Signal):
        assert False, "unexpected failure"

    monkeypatch.setattr(KernelInitFlow, "boot_userapp", fail)
    with pytest.raises(AssertionError, match="unexpected failure"):
        main()
    assert gv.scheduler is not None
    assert gv.scheduler.current is gv.kernel_init_task


def test_boot_assertion_before_scheduler_initialization_propagates(monkeypatch):
    def fail(self: BootInitFlow, sig: Signal):
        assert False, "early setup failed"

    monkeypatch.setattr(BootInitFlow, "early_setup", fail)
    with pytest.raises(AssertionError, match="early setup failed"):
        gv.computer.drive(TaskLocalEnv(), gv.kernel, "boot")
    assert gv.scheduler is None
    assert gv.boot_init_task.env.depth == 0
    assert gv.boot_init_task.env.signal_queues == []


def test_boot_task_cannot_be_started_twice(monkeypatch):
    def finish(self: BootInitFlow, sig: Signal):
        pass

    monkeypatch.setattr(BootInitFlow, "arch_boot", finish)
    gv.computer.drive(TaskLocalEnv(), gv.kernel, "boot")
    assert gv.boot_init_task.state is TaskState.FINISHED
    with pytest.raises(AssertionError, match="already been started"):
        gv.computer.drive(TaskLocalEnv(), gv.kernel, "boot")


def test_global_objects_create_only_task_zero_before_boot_and_reset_after_stop():
    first = GlobalVars()
    second = GlobalVars()
    first.boot_init_task.env.cv.local_irq = 7
    first.kernel_init_flow.visibility.local_irq = 0
    for objects in (first, second):
        assert isinstance(objects.boot_init_task, BootInitTask)
        assert isinstance(objects.boot_init_task.flow, BootInitFlow)
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
    assert first.boot_init_task.flow is not second.boot_init_task.flow
    assert second.boot_init_task.env.cv.local_irq == 0
    assert second.kernel_init_flow.visibility.local_irq == 1
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    old_task = gv.boot_init_task
    old_scheduler = gv.scheduler
    old_init = gv.kernel_init_task
    old_kthreadd = gv.kthreadd_task
    gv.reset()
    assert gv.boot_init_task is not old_task
    assert gv.scheduler is gv.kernel_init_task is gv.kthreadd_task is None
    assert gv.boot_init_task.env.cv.local_irq == 0
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert gv.scheduler is not old_scheduler
    assert gv.kernel_init_task is not old_init
    assert gv.kthreadd_task is not old_kthreadd
