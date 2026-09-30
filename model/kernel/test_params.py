"""Test Parsing Params"""

from global_vars import gv


def test_parsing_early_params():
    gv.reset()

    gv.computer.drive(gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi)
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    gv.computer.drive(gv.kernel_param_table, "register", param=gv.earlycon_param)

    gv.computer.drive(gv.boot_command_line, "add", key="earlycon", val="sbi")
    gv.computer.drive(gv.boot_command_line, "parse", early=True)

    assert gv.early_console_dev.console.ready
