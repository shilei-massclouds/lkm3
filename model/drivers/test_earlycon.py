"""Test EarlyCon Driver Table"""

from global_vars import gv
from sync import ContentionEnv


def test_earlycon_drv_table():
    gv.reset()
    ce = ContentionEnv()

    gv.computer.drive(
        ce, gv.earlycon_driver_table, "register", drv=gv.earlycon_riscv_sbi
    )
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]

    gv.computer.drive(ce, gv.earlycon_driver_table, "probe", drv="sbi")
    assert gv.early_console_dev.console.ready
