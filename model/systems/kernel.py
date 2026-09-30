"""Kernel System"""

from dataclasses import dataclass

from engine import Signal, System


@dataclass
class Kernel(System):
    def __repr__(self):
        return "Kernel"

    def setup(self, sig: Signal):
        from global_vars import gv

        self.drive(gv.kernel_param_table, "register", param=gv.earlycon_param)
        self.drive(gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi)

        self.drive(gv.boot_command_line, "add", key="earlycon", val="sbi")

    def boot(self, sig: Signal):
        from global_vars import gv

        self.drive(gv.boot_init_flow, "arch_boot")
