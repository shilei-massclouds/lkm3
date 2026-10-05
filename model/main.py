"""Derive Entry"""

import asyncio
from copy import copy

from framework.sync import EXCLUSIVE_CV, ContentionVector
from global_vars import gv


async def kernel_boot(cv: ContentionVector) -> None:
    gv.computer.drive(cv, gv.kernel, "boot")


def main() -> None:
    cv = copy(EXCLUSIVE_CV)
    gv.computer.drive(cv, gv.kernel, "setup")
    asyncio.run(kernel_boot(cv))


if __name__ == "__main__":
    main()
