"""Test EarlyCon Driver Table"""

from framework.sync import ContentionVector
from global_vars import gv


def test_earlycon_drv_table():
    gv.reset()
    ce = ContentionVector.ones()

    gv.computer.drive(
        ce, gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi
    )
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    gv.computer.drive(ce, gv.earlycon_driver_table, "probe", drv="sbi")
    assert gv.early_console_dev.console.ready
