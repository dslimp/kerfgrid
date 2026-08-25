.PHONY: install test serve smoke acceptance

install:
	python3 -m pip install -e '.[dev]'

test:
	python3 -m pytest -q

serve:
	python3 server.py --host 127.0.0.1 --port 8765

smoke:
	bash tests/playwright_smoke.sh

acceptance:
	python3 tools/shop_acceptance.py
