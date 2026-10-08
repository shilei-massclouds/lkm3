"""BootInitTask Flow"""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal
from framework.scheduler import Scheduler
from framework.sync_primitives import LocalIrq, LocalMultiTasks, Preemption
from kernel.task import KernelInitTask, KThreaddTask


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

    def spawn_tasks(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is not None
        assert gv.kernel_init_task is None and gv.kthreadd_task is None, (
            "initial tasks have already been created"
        )
        gv.kernel_init_task = KernelInitTask()
        self.drive(sig.env, gv.kernel_init_task, "setup")
        self.drive(sig.env, gv.kernel_init_task, "enable")

        gv.kthreadd_task = KThreaddTask()
        self.drive(sig.env, gv.kthreadd_task, "setup")
        self.drive(sig.env, gv.kthreadd_task, "enable")

        sig.chain(self, "yield_current")

    def yield_current(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is not None
        LocalMultiTasks().enable(sig.env.cv)
        # RemoteCpus().enable(sig.env.cv)
        # Like schedule_preempt_disabled(), task 0 retains disabled preemption.
        Preemption().disable(sig.env.cv)
        self.drive(sig.env, gv.scheduler, "schedule")
        sig.chain(self, "enter_idle")

    def enter_idle(self, sig: Signal):
        for _ in range(3):
            self.drive(sig.env, self, "do_idle")

    def do_idle(self, sig: Signal):
        assert sig.env.task is not None
        self.drive(sig.env, sig.env.task._scheduler(), "schedule")
