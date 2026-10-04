"""Test Parsing Params"""

from copy import copy

from framework.sync import EXCLUSIVE_CV
from global_vars import gv


def test_parsing_early_params():
    gv.reset()
    cv = copy(EXCLUSIVE_CV)

    gv.computer.drive(
        cv, gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi
    )
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    gv.computer.drive(cv, gv.kernel_param_table, "register", param=gv.earlycon_param)

    gv.computer.drive(cv, gv.boot_command_line, "add", key="earlycon", val="sbi")
    gv.computer.drive(cv, gv.boot_command_line, "parse", early=True)

    assert gv.early_console_dev.console.ready
