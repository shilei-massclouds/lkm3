MAKEFLAGS += --no-print-directory

CARGO ?= cargo
RUST_TARGET ?= riscv64imac-unknown-none-elf

test:
	$(MAKE) fmt
	$(MAKE) clippy

fmt:
	$(CARGO) fmt --all -- --check

clippy:
	$(CARGO) clippy --workspace --target $(RUST_TARGET) -- -D warnings

.PHONY: test fmt clippy
