PY ?= python3.12
PIPX ?= pipx

.PHONY: help install test lint clean

help:
	@echo "Targets:"
	@echo "  install     pipx install --editable . (host CLI install)"
	@echo "  test        run pytest"
	@echo "  lint        run ruff"
	@echo "  clean       remove build artifacts"

install:
	$(PIPX) install --editable . --python $(PY)

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

clean:
	rm -rf dist build *.egg-info \
	       .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
