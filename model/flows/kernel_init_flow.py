"""Kernel initialization up to the temporary user application boundary."""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal


@dataclass
class KernelInitFlow(TaskFlow):
    def pre_smp(self, sig: Signal):
        sig.chain(self, "bringup_nonboot_cpus")

    def bringup_nonboot_cpus(self, sig: Signal):
        # RemoteCpus().enable(sig.env.cv)
        sig.chain(self, "final_init")

    def final_init(self, sig: Signal):
        sig.chain(self, "boot_userapp")

    def boot_userapp(self, sig: Signal):
        from framework.engine import terminate

        terminate("\t[Terminate: Reach UserApp]")
