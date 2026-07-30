.PHONY: install dev test lint typecheck imports lock pre-commit fmt clean

PYTHON ?= python

install:
	pip install -e .

dev:
	pip install -e ".[dev,ui,web]"
	pre-commit install || true

test:
	pytest

lint:
	ruff check .

fmt:
	ruff check --fix .
	ruff format .

typecheck:
	mypy lemely

imports:
	lint-imports

pre-commit:
	pre-commit run --all-files

lock:
	uv lock

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
