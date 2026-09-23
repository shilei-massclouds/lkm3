MAKEFLAGS += --no-print-directory

CARGO ?= cargo
CARGO_MANIFEST := workspace/Cargo.toml
CARGO_TARGET_DIR := workspace/target
LKM_OBJ_DIR := workspace/lkm_objs
RUST_TARGET ?= riscv64imac-unknown-none-elf
DEBUG ?= n

include workspace/Makefile.util

components := $(call workspace-components)

ifeq ($(DEBUG),n)
CARGO_PROFILE := --release
endif

build: $(components)

$(components): FORCE | $(LKM_OBJ_DIR)
	$(CARGO) rustc --manifest-path $(CARGO_MANIFEST) -p $@ --lib --target $(RUST_TARGET) $(CARGO_PROFILE) -- --emit=obj="$(abspath $(LKM_OBJ_DIR)/$(call workspace-object,$@))" -C codegen-units=1

$(LKM_OBJ_DIR):
	@mkdir -p "$@"

FORCE:

test:
	$(MAKE) fmt
	$(MAKE) clippy
	$(MAKE) unittest

fmt:
	$(CARGO) fmt --manifest-path $(CARGO_MANIFEST) --all -- --check

clippy:
	$(CARGO) clippy --manifest-path $(CARGO_MANIFEST) --workspace --target $(RUST_TARGET) $(CARGO_PROFILE) -- -D warnings

unittest:
	$(CARGO) test --manifest-path $(CARGO_MANIFEST) --workspace $(CARGO_PROFILE)

clean:
	$(CARGO) clean --manifest-path $(CARGO_MANIFEST) --target-dir $(CARGO_TARGET_DIR)
	rm -rf -- "$(LKM_OBJ_DIR)"

.PHONY: build FORCE test fmt clippy unittest clean
