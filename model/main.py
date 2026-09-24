#!/usr/bin/env python3

from engine import drive


def derive_kernel():
    from kernel import Kernel
    kernel = Kernel()

    drive(kernel, "boot")
    print("Derive kernel ok!")


def main() -> None:
    derive_kernel()


if __name__ == "__main__":
    main()
