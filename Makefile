# GridCast — convenience targets. On Windows run the same commands via Git Bash,
# or invoke the venv interpreter directly: .venv/Scripts/python -m pytest
PY := .venv/Scripts/python
ifeq ($(OS),Windows_NT)
else
PY := .venv/bin/python
endif

.PHONY: setup test lint ingest

setup:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

ingest:
	$(PY) -m gridcast.ingest --all
