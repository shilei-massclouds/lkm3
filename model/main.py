"""Derive Entry"""

from framework.engine import TaskLocalEnv
from global_vars import gv


def main() -> None:
    setup_env = TaskLocalEnv()
    gv.computer.drive(setup_env, gv.kernel, "setup")
    boot_env = TaskLocalEnv()
    gv.computer.drive(boot_env, gv.kernel, "boot")


if __name__ == "__main__":
    main()
