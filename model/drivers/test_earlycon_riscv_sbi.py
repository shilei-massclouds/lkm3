from engine import drive
from global_vars import gv

def test_earlycon_riscv_sbi():
    global gv
    gv.reset()
    drive(gv.earlycon_riscv_sbi, "setup", drv="sbi")
    assert gv.early_console_dev.console.ready
