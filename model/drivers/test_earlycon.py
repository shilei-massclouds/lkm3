from drivers.earlycon import EarlyConDrvTable, EarlyCon
from drivers.earlycon_riscv_sbi import EarlyConRiscvSBI
from engine import drive

def test_earlycon_drv_table():
    drv_sbi = EarlyConRiscvSBI()
    drv_table = EarlyConDrvTable()
    drive(drv_table, "register", drv=drv_sbi)
    assert drv_table.table == [drv_sbi]

    dev = EarlyCon()
    drive(drv_table, "probe", drv_type="sbi", dev=dev)
    assert dev.console.ready
