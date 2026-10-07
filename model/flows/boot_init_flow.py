"""BootInitTask Flow"""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal, requires_cv
from framework.scheduler import Scheduler
from framework.sync import ContentionVector, LocalIrq, LocalMultiTasks, Preemption
from kernel.task import KernelInitTask, Task


@dataclass
class BootInitFlow(TaskFlow):
    def arch_boot(self, sig: Signal):
        sig.chain(self, "early_setup")

    def early_setup(self, sig: Signal):
        from global_vars import gv

        self.drive(sig.env, gv.io, "printk", msg="banner")
        self.drive(sig.env, gv.boot_command_line, "parse", early=True)
        sig.chain(self, "sched_init")

    def sched_init(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is None, "scheduler has already been initialized"
        scheduler = Scheduler()
        self.drive(sig.env, scheduler, "setup")
        gv.scheduler = scheduler
        sig.chain(self, "enable_irq")

    def enable_irq(self, sig: Signal):
        from global_vars import gv

        LocalIrq().enable(sig.env.cv)
        self.drive(sig.env, gv.io, "printk", msg="local irq enabled.")
        sig.chain(self, "spawn_tasks")

    @requires_cv(ContentionVector(zero=True, local_irq=1))
    def spawn_tasks(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is not None
        assert gv.kernel_init_task is None and gv.kthreadd_task is None, (
            "initial tasks have already been created"
        )
        gv.kernel_init_task = KernelInitTask(
            "kernel_init",
            gv.kernel_init_flow,
            "pre_smp",
            ContentionVector(zero=True, local_irq=1, local_tasks=1),
            gv.scheduler,
            pid=1,
        )
        self.drive(sig.env, gv.kernel_init_task, "setup")
        self.drive(sig.env, gv.kernel_init_task, "enable")

        gv.kthreadd_task = Task(
            "kthreadd",
            gv.kthreadd_flow,
            "wait_for_work",
            ContentionVector(zero=True, local_irq=1, local_tasks=1),
            gv.scheduler,
            pid=2,
        )
        self.drive(sig.env, gv.kthreadd_task, "setup")
        self.drive(sig.env, gv.kthreadd_task, "enable")

        sig.chain(self, "yield_current")

    @requires_cv(ContentionVector(zero=True, local_irq=1))
    def yield_current(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is not None
        LocalMultiTasks().enable(sig.env.cv)
        # Like schedule_preempt_disabled(), task 0 retains disabled preemption.
        Preemption().disable(sig.env.cv)
        self.drive(sig.env, gv.scheduler, "schedule")
        sig.chain(self, "enter_idle")

    @requires_cv(ContentionVector(zero=True, local_irq=1))
    def enter_idle(self, sig: Signal):
        for _ in range(3):
            self.drive(sig.env, self, "do_idle")

    @requires_cv(ContentionVector(local_tasks=0))
    def do_idle(self, sig: Signal):
        assert sig.env.task is not None
        self.drive(sig.env, sig.env.task.require_scheduler(), "schedule")
