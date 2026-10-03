"""Derive Entry"""

from framework.sync import ContentionEnv
from global_vars import gv


def main() -> None:
    ce = ContentionEnv()
    gv.computer.drive(ce, gv.kernel, "setup")
    gv.computer.drive(ce, gv.kernel, "boot")


if __name__ == "__main__":
    main()
