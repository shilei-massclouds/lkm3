"""Test EarlyCon Riscv SBI Driver"""

from framework.engine import TaskLocalEnv
from global_vars import gv


def test_earlycon_riscv_sbi():
    gv.reset()
    env = TaskLocalEnv()
    gv.computer.drive(env, gv.earlycon_riscv_sbi, "_setup", drv="sbi")
    assert gv.early_console_dev.console.ready
