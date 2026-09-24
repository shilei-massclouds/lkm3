#!/usr/bin/env python3
from engine import emit, process

def derive_kernel():
    from kernel import Kernel
    kernel = Kernel()
    emit(kernel, "boot")
    process()
    print("Derive kernel ok!")


def main() -> None:
    derive_kernel()


if __name__ == "__main__":
    main()
