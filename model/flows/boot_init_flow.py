"""BootInitTask Flow"""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal
from framework.scheduler import Scheduler
from framework.sync_primitives import LocalIrq, LocalMultiTasks, Preemption, RemoteCpus
from kernel.task import KernelInitTask, KThreaddTask


@dataclass
class BootInitFlow(TaskFlow):
    def _arch_boot(self, sig: Signal):
        sig.chain(self, "_early_setup")

    def _early_setup(self, sig: Signal):
        from global_vars import gv

        self.drive(sig.env, gv.io, "printk", msg="banner")
        self.drive(sig.env, gv.boot_command_line, "_parse", early=True)
        sig.chain(self, "_sched_init")

    def _sched_init(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is None, "scheduler has already been initialized"
        scheduler = Scheduler()
        self.drive(sig.env, scheduler, "_setup")
        gv.scheduler = scheduler
        sig.chain(self, "_enable_irq")

    def _enable_irq(self, sig: Signal):
        from global_vars import gv

        LocalIrq().enable(sig.env.cv)
        self.drive(sig.env, gv.io, "printk", msg="local irq enabled.")
        sig.chain(self, "_spawn_tasks")

    def _spawn_tasks(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is not None
        assert gv.kernel_init_task is None and gv.kthreadd_task is None, (
            "initial tasks have already been created"
        )
        gv.kernel_init_task = KernelInitTask()
        self.drive(sig.env, gv.kernel_init_task, "_setup")
        self.drive(sig.env, gv.kernel_init_task, "_wake_up_new_task")

        gv.kthreadd_task = KThreaddTask()
        self.drive(sig.env, gv.kthreadd_task, "_setup")
        self.drive(sig.env, gv.kthreadd_task, "_wake_up_new_task")

        sig.chain(self, "_yield_current")

    def _yield_current(self, sig: Signal):
        from global_vars import gv

        assert gv.scheduler is not None
        LocalMultiTasks().enable(sig.env.cv)
        RemoteCpus().enable(sig.env.cv)
        # Like schedule_preempt_disabled(), task 0 retains disabled preemption.
        Preemption().disable(sig.env.cv)
        self.drive(sig.env, gv.scheduler, "_schedule")
        sig.chain(self, "_enter_idle")

    def _enter_idle(self, sig: Signal):
        for _ in range(3):
            self.drive(sig.env, self, "_do_idle")

    def _do_idle(self, sig: Signal):
        assert sig.env.task is not None
        self.drive(sig.env, sig.env.task._scheduler(), "_schedule")
