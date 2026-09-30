"""Test EarlyCon Driver Table"""

from engine import drive
from global_vars import gv


def test_earlycon_drv_table():
    global gv
    gv.reset()

    drive(gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi)
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    drive(gv.earlycon_driver_table, "probe", drv="sbi")
    assert gv.early_console_dev.console.ready
