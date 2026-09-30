PYTHON ?= python3
RUFF ?= ruff
PYRIGHT ?= pyright
MAKEFLAGS += --no-print-directory

run:
	@$(PYTHON) main.py

test:
	@$(RUFF) check .
	@$(RUFF) format --check .
	@$(PYRIGHT) .
	pytest -q

.PHONY: run test
