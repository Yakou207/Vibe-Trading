.PHONY: check-env test dashboard

PYTHON ?= .venv/bin/python

check-env:
	$(PYTHON) scripts/check_env.py

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests

dashboard:
	PYTHONPATH=src $(PYTHON) -m streamlit run src/fintech_quant/reports/dashboard.py
