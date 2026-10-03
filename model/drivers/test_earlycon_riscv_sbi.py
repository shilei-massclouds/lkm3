from global_vars import gv
from sync import ContentionEnv


def test_earlycon_riscv_sbi():
    gv.reset()
    ce = ContentionEnv()
    gv.computer.drive(ce, gv.earlycon_riscv_sbi, "setup", drv="sbi")
    assert gv.early_console_dev.console.ready
