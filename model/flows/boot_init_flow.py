"""BootInitTask Flow"""

from dataclasses import dataclass

from framework.engine import Signal, System, requires_cv
from framework.sync import ContentionVector, LocalIrq, LocalMultiTasks


@dataclass
class BootInitFlow(System):
    def arch_boot(self, sig: Signal):
        sig.chain(self, "early_setup")

    def early_setup(self, sig: Signal):
        from global_vars import gv

        self.drive(sig.engine.cv, gv.io, "printk", msg="banner")
        self.drive(sig.engine.cv, gv.boot_command_line, "parse", early=True)
        sig.chain(self, "enable_irq")

    def enable_irq(self, sig: Signal):
        from global_vars import gv

        LocalIrq().enable(sig.engine.cv)
        self.drive(sig.engine.cv, gv.io, "printk", msg="local irq enabled.")
        sig.chain(self, "spawn_tasks")

    @requires_cv(ContentionVector(zero=True, local_irq=1))
    def spawn_tasks(self, sig: Signal):
        sig.chain(self, "yield_current")

    @requires_cv(ContentionVector(zero=True, local_irq=1))
    def yield_current(self, sig: Signal):
        LocalMultiTasks().enable(sig.engine.cv)
        sig.chain(self, "enter_idle")

    @requires_cv(ContentionVector(zero=True, local_irq=1, local_tasks=1))
    def enter_idle(self, sig: Signal):
        pass
