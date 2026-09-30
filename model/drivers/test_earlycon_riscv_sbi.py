from global_vars import gv


def test_earlycon_riscv_sbi():
    gv.reset()
    gv.computer.drive(gv.earlycon_riscv_sbi, "setup", drv="sbi")
    assert gv.early_console_dev.console.ready
