MAKEFLAGS += --no-print-directory
PYTHON ?= python3
RUFF ?= ruff
PYRIGHT ?= pyright
DEBUG ?= n
export DEBUG

run:
	@$(PYTHON) main.py

test:
	@$(RUFF) check .
	@$(RUFF) format --check .
	@$(PYRIGHT) .
	pytest -q

.PHONY: run test
