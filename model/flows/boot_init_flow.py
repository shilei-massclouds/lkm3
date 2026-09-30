"""BootInitTask Flow"""

from dataclasses import dataclass

from engine import Signal, System


@dataclass
class BootInitFlow(System):
    def arch_boot(self, sig: Signal):
        sig.engine.emit(self, "early_setup")

    def early_setup(self, sig: Signal):
        from global_vars import gv

        self.drive(gv.boot_command_line, "parse", early=True)
        sig.engine.emit(self, "enable_irq")

    def enable_irq(self, sig: Signal):
        sig.engine.emit(self, "spawn_tasks")

    def spawn_tasks(self, sig: Signal):
        sig.engine.emit(self, "yield_current")

    def yield_current(self, sig: Signal):
        sig.engine.emit(self, "enter_idle")

    def enter_idle(self, sig: Signal):
        pass
