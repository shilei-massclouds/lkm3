"""Test Kernel Setup"""

from copy import copy

from framework.sync import EXCLUSIVE_CV
from global_vars import gv


def test_kernel_setup():
    gv.reset()
    ce = copy(EXCLUSIVE_CV)

    gv.computer.drive(ce, gv.kernel, "setup")

    assert gv.kernel_param_table.table == [gv.earlycon_param]
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]
    items = [(item.key, item.val) for item in gv.boot_command_line.items]
    assert items == [("earlycon", "sbi")]
