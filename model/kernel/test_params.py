"""Test Parsing Params"""

from engine import drive
from global_vars import gv


def test_parsing_early_params():
    gv.reset()

    drive(gv.computer, gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi)
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    drive(gv.computer, gv.kernel_param_table, "register", param=gv.earlycon_param)

    drive(gv.computer, gv.boot_command_line, "add", key="earlycon", val="sbi")
    drive(gv.computer, gv.boot_command_line, "parse", early=True)

    assert gv.early_console_dev.console.ready
