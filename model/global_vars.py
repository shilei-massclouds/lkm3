"""Context for Global vars"""

from dataclasses import dataclass, field

from drivers.earlycon import EarlyCon, EarlyConDrvTable, EarlyConParam
from drivers.earlycon_riscv_sbi import EarlyConRiscvSBI
from kernel.params import CmdLine, ParamTable


@dataclass
class GlobalVars:
    earlycon_param: EarlyConParam = field(default_factory=EarlyConParam)
    earlycon_driver_table: EarlyConDrvTable = field(default_factory=EarlyConDrvTable)
    early_console_dev: EarlyCon = field(default_factory=EarlyCon)
    earlycon_riscv_sbi: EarlyConRiscvSBI = field(default_factory=EarlyConRiscvSBI)
    boot_command_line: CmdLine = field(default_factory=CmdLine)
    kernel_param_table: ParamTable = field(default_factory=ParamTable)

    def reset(self):
        self.__init__()


gv = GlobalVars()
