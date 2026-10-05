"""Test Kernel Setup and Boot"""

from copy import copy

from framework.sync import EXCLUSIVE_CV
from global_vars import gv


def test_kernel_setup():
    gv.reset()
    cv = copy(EXCLUSIVE_CV)

    gv.computer.drive(cv, gv.kernel, "setup")

    assert gv.kernel_param_table.table == [gv.earlycon_param]
    assert gv.earlycon_driver_table.table == [gv.earlycon_riscv_sbi]
    items = [(item.key, item.val) for item in gv.boot_command_line.items]
    assert items == [("earlycon", "sbi")]


def test_kernel_boot():
    gv.reset()
    cv = copy(EXCLUSIVE_CV)

    gv.computer.drive(cv, gv.kernel, "setup")
    gv.computer.drive(cv, gv.kernel, "boot")

    assert (cv.local_irq, cv.local_tasks, cv.remote_irq, cv.remote_tasks) == (
        1,
        0,
        0,
        0,
    )
