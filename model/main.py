"""Derive Entry"""

from framework.engine import DerivationStopped, TaskLocalEnv
from global_vars import gv


def main() -> None:
    env = TaskLocalEnv()
    gv.computer.drive(env, gv.kernel, "setup")
    try:
        gv.computer.drive(env, gv.kernel, "boot")
    except DerivationStopped as stopped:
        print(f"Derivation stopped at {stopped}.")


if __name__ == "__main__":
    main()
