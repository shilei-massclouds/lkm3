from framework.sync import ContentionVector
from global_vars import gv


def test_earlycon_riscv_sbi():
    gv.reset()
    ce = ContentionVector.ones()
    gv.computer.drive(ce, gv.earlycon_riscv_sbi, "setup", drv="sbi")
    assert gv.early_console_dev.console.ready
