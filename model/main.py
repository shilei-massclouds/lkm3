"""Derive Entry"""

from framework.engine import TaskLocalEnv
from global_vars import gv


def main() -> None:
    setup_env = TaskLocalEnv()
    gv.computer.drive(setup_env, gv.kernel, "_setup")
    boot_env = TaskLocalEnv()
    gv.computer.drive(boot_env, gv.kernel, "_boot")


if __name__ == "__main__":
    main()
