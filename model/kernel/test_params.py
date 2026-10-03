"""Test Parsing Params"""

from global_vars import gv
from sync import ContentionEnv


def test_parsing_early_params():
    gv.reset()
    ce = ContentionEnv()

    gv.computer.drive(
        ce, gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi
    )
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    gv.computer.drive(ce, gv.kernel_param_table, "register", param=gv.earlycon_param)

    gv.computer.drive(ce, gv.boot_command_line, "add", key="earlycon", val="sbi")
    gv.computer.drive(ce, gv.boot_command_line, "parse", early=True)

    assert gv.early_console_dev.console.ready
