from drivers.earlycon import EarlyCon
from drivers.earlycon_riscv_sbi import EarlyConRiscvSBI
from engine import drive

def test_earlycon_riscv_sbi():
    dev = EarlyCon()
    drv = EarlyConRiscvSBI()
    drive(drv, "setup", drv_type="sbi", dev=dev)
