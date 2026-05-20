PY ?= python3.12
PIPX ?= pipx

.PHONY: help install test lint bundle clean

help:
	@echo "Targets:"
	@echo "  install     pipx install --editable . (host CLI install)"
	@echo "  test        run pytest"
	@echo "  lint        run ruff"
	@echo "  bundle      build asdd-bundle.tar.gz for transport to another Mac"
	@echo "  clean       remove build artifacts"

install:
	$(PIPX) install --editable . --python $(PY)

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

bundle:
	@mkdir -p bundle-staging/asdd-bundle
	@cp -R asdd docker project_skeleton bundle-staging/asdd-bundle/
	@cp pyproject.toml README.md USER_GUIDE.md bundle-staging/asdd-bundle/
	@find bundle-staging -type d -name __pycache__ -prune -exec rm -rf {} +
	@find bundle-staging -type f -name '*.pyc' -delete
	@tar --owner=0 --group=0 -czf asdd-bundle.tar.gz -C bundle-staging asdd-bundle
	@rm -rf bundle-staging
	@ls -lh asdd-bundle.tar.gz

clean:
	rm -rf bundle-staging asdd-bundle.tar.gz dist build *.egg-info \
	       .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
