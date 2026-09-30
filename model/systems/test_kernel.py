"""Test Kernel Setup"""

from global_vars import gv


def test_kernel_setup():
    gv.reset()

    gv.computer.drive(gv.kernel, "setup")

    assert gv.kernel_param_table.table == [gv.earlycon_param]
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]
    items = [(item.key, item.val) for item in gv.boot_command_line.items]
    assert items == [("earlycon", "sbi")]
