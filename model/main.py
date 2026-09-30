"""Derive Entry"""

from engine import drive
from global_vars import gv


def main() -> None:
    drive(gv.computer, gv.kernel, "setup")
    drive(gv.computer, gv.kernel, "boot")


if __name__ == "__main__":
    main()
