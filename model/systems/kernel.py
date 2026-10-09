"""Kernel System"""

from dataclasses import dataclass

from framework.engine import Signal, System


@dataclass
class Kernel(System):
    def __repr__(self):
        return "Kernel"

    def _setup(self, sig: Signal):
        from global_vars import gv

        self.drive(sig.env, gv.kernel_param_table, "_register", param=gv.earlycon_param)
        self.drive(
            sig.env,
            gv.earlycon_driver_table,
            "_register",
            drv=gv.earlycon_riscv_sbi,
        )

        self.drive(sig.env, gv.boot_command_line, "_add", key="earlycon", val="sbi")

    def _boot(self, sig: Signal):
        from global_vars import gv

        self.drive(sig.env, gv.boot_init_task, "_start")
