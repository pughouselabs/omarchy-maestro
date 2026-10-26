.PHONY: test lint build

test:
	python3 -m unittest discover -s tests

lint:
	ruff check .

build:
	python3 -m build
