MAKEFLAGS += --no-print-directory

CARGO ?= cargo
RUST_TARGET ?= riscv64imac-unknown-none-elf
DEBUG ?= n

ifeq ($(DEBUG),n)
CARGO_PROFILE := --release
endif

test:
	$(MAKE) fmt
	$(MAKE) clippy

fmt:
	$(CARGO) fmt --all -- --check

clippy:
	$(CARGO) clippy --workspace --target $(RUST_TARGET) $(CARGO_PROFILE) -- -D warnings

.PHONY: test fmt clippy
