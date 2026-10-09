"""Test Parsing Params"""

from framework.engine import TaskLocalEnv
from global_vars import gv


def test_parsing_early_params():
    gv.reset()
    env = TaskLocalEnv()

    gv.computer.drive(
        env, gv.earlycon_driver_table, "_register", drv=gv.earlycon_riscv_sbi
    )
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    gv.computer.drive(env, gv.kernel_param_table, "_register", param=gv.earlycon_param)

    gv.computer.drive(env, gv.boot_command_line, "_add", key="earlycon", val="sbi")
    gv.computer.drive(env, gv.boot_command_line, "_parse", early=True)

    assert gv.early_console_dev.console.ready
