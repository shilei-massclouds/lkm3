MAKEFLAGS += --no-print-directory

CARGO ?= cargo
CARGO_MANIFEST := workspace/Cargo.toml
RUST_TARGET ?= riscv64imac-unknown-none-elf
DEBUG ?= n

ifeq ($(DEBUG),n)
CARGO_PROFILE := --release
endif

test:
	$(MAKE) fmt
	$(MAKE) clippy
	$(MAKE) cargo-test

fmt:
	$(CARGO) fmt --manifest-path $(CARGO_MANIFEST) --all -- --check

clippy:
	$(CARGO) clippy --manifest-path $(CARGO_MANIFEST) --workspace --target $(RUST_TARGET) $(CARGO_PROFILE) -- -D warnings

cargo-test:
	$(CARGO) test --manifest-path $(CARGO_MANIFEST) --workspace $(CARGO_PROFILE)

clean:
	$(CARGO) clean --manifest-path $(CARGO_MANIFEST) --target-dir workspace/target

.PHONY: test fmt clippy cargo-test clean
