"""Derive Entry"""

from framework.sync import ContentionVector
from global_vars import gv


def main() -> None:
    ce = ContentionVector.ones()
    gv.computer.drive(ce, gv.kernel, "setup")
    gv.computer.drive(ce, gv.kernel, "boot")


if __name__ == "__main__":
    main()
