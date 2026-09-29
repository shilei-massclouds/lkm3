"""Riscv SBI Earlycon Driver"""

from dataclasses import dataclass
from drivers.earlycon import EarlyConDrv
from engine import Signal, drive

@dataclass
class EarlyConRiscvSBI(EarlyConDrv):
    def setup(self, sig: Signal):
        if sig.args["drv_type"] == "sbi":
            drive(sig.args["dev"], "setup", drv="sbi")
