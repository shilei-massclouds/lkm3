"""Derive Entry"""

from global_vars import gv
from sync import ContentionEnv


def main() -> None:
    ce = ContentionEnv()
    gv.computer.drive(ce, gv.kernel, "setup")
    gv.computer.drive(ce, gv.kernel, "boot")


if __name__ == "__main__":
    main()
