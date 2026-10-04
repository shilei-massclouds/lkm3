"""Riscv SBI Earlycon Driver"""

from dataclasses import dataclass

from drivers.earlycon import EarlyConDrv
from framework.engine import Signal


@dataclass
class EarlyConRiscvSBI(EarlyConDrv):
    def setup(self, sig: Signal):
        from global_vars import gv

        if sig.args["drv"] == "sbi":
            self.drive(sig.engine.cv, gv.early_console_dev, "setup", drv="sbi")
