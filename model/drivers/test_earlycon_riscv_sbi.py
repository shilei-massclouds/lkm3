from engine import drive
from global_vars import gv


def test_earlycon_riscv_sbi():
    gv.reset()
    drive(gv.computer, gv.earlycon_riscv_sbi, "setup", drv="sbi")
    assert gv.early_console_dev.console.ready
