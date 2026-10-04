"""Derive Entry"""

from copy import copy

from framework.sync import EXCLUSIVE_CV
from global_vars import gv


def main() -> None:
    ce = copy(EXCLUSIVE_CV)
    gv.computer.drive(ce, gv.kernel, "setup")
    gv.computer.drive(ce, gv.kernel, "boot")


if __name__ == "__main__":
    main()
