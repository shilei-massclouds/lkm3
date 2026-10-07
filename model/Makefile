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

clean:
	@find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	@find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

.PHONY: run test clean
