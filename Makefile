PYTHON ?= python3
.PHONY: run test backtest evaluate format-check
run:
	$(PYTHON) scripts/run_demo.py
test:
	$(PYTHON) -m unittest -v
backtest:
	$(PYTHON) temporal.py
evaluate:
	$(PYTHON) evaluate.py
format-check:
	$(PYTHON) -m black --check *.py scripts/*.py
