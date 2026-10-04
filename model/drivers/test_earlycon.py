"""Test EarlyCon Driver Table"""

from copy import copy

from framework.sync import EXCLUSIVE_CV
from global_vars import gv


def test_earlycon_drv_table():
    gv.reset()
    ce = copy(EXCLUSIVE_CV)

    gv.computer.drive(
        ce, gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi
    )
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    gv.computer.drive(ce, gv.earlycon_driver_table, "probe", drv="sbi")
    assert gv.early_console_dev.console.ready
