"""Kernel initialization up to the temporary user application boundary."""

from dataclasses import dataclass

from flows.task_flow import TaskFlow
from framework.engine import Signal
from framework.sync_primitives import RemoteCpus


@dataclass
class KernelInitFlow(TaskFlow):
    def _pre_smp(self, sig: Signal):
        sig.chain(self, "_bringup_nonboot_cpus")

    def _bringup_nonboot_cpus(self, sig: Signal):
        RemoteCpus().enable(sig.env.cv)
        sig.chain(self, "_final_init")

    def _final_init(self, sig: Signal):
        sig.chain(self, "_boot_userapp")

    def _boot_userapp(self, sig: Signal):
        from framework.engine import terminate

        terminate("\t[Terminate: Reach UserApp]")
