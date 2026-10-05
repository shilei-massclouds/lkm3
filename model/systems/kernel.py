"""Kernel System"""

from dataclasses import dataclass

from framework.engine import Signal, System


@dataclass
class Kernel(System):
    def __repr__(self):
        return "Kernel"

    def setup(self, sig: Signal):
        from global_vars import gv

        self.drive(sig.env, gv.kernel_param_table, "register", param=gv.earlycon_param)
        self.drive(
            sig.env,
            gv.earlycon_driver_table,
            "register",
            drv=gv.earlycon_riscv_sbi,
        )

        self.drive(sig.env, gv.boot_command_line, "add", key="earlycon", val="sbi")

    def boot(self, sig: Signal):
        from global_vars import gv

        gv.boot_init_task.start()
