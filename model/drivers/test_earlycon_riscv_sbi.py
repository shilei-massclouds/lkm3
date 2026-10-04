"""Test EarlyCon Riscv SBI Driver"""

from copy import copy

from framework.sync import EXCLUSIVE_CV
from global_vars import gv


def test_earlycon_riscv_sbi():
    gv.reset()
    cv = copy(EXCLUSIVE_CV)
    gv.computer.drive(cv, gv.earlycon_riscv_sbi, "setup", drv="sbi")
    assert gv.early_console_dev.console.ready
