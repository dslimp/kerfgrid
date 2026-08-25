# Contributing

Read `AGENTS.md` and the relevant document under `docs/contracts/` before
changing behavior.

## Setup

```sh
python -m pip install -e '.[dev]'
```

## Checks

```sh
python -m pytest -q
python -m compileall -q plasma_cam server.py
```

For UI or API changes, restart the canonical local server and run the browser
acceptance:

```sh
python server.py --host 127.0.0.1 --port 8765
bash tests/playwright_smoke.sh
```

Every geometry, nesting, export, or browser-flow bug fix needs a focused
regression test. Validation findings remain warnings and must not disable
operator-controlled export.
