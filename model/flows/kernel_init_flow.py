"""Kernel initialization up to the temporary user application boundary."""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal, requires_cv
from framework.sync import ContentionVector


@requires_cv(ContentionVector(zero=True, local_irq=1, local_tasks=1))
@dataclass
class KernelInitFlow(TaskFlow):
    def pre_smp(self, sig: Signal):
        sig.chain(self, "bringup_nonboot_cpus")

    def bringup_nonboot_cpus(self, sig: Signal):
        sig.chain(self, "final_init")

    def final_init(self, sig: Signal):
        sig.chain(self, "boot_userapp")

    def boot_userapp(self, sig: Signal):
        from framework.engine import terminate

        terminate("\t[Reach UserApp]")
