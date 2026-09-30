"""Derive Entry"""

from global_vars import gv


def main() -> None:
    gv.computer.drive(gv.kernel, "setup")
    gv.computer.drive(gv.kernel, "boot")


if __name__ == "__main__":
    main()
