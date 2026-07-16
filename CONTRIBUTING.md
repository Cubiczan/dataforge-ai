# Contributing to DataForge AI

Contributions are welcome! This project is built in the open under the Apache 2.0 license.

## Development setup

```bash
git clone https://github.com/Cubiczan/dataforge-ai.git
cd dataforge-ai
pip install -e ".[dev]"
pre-commit install
```

## Running tests

```bash
pytest                          # unit tests
pytest --integration            # integration tests (requires local DataHub)
```

## Code style

- Python 3.10+
- `ruff` for linting + formatting (line length 110)
- `mypy --strict` for type checking
- All public functions have docstrings

## Adding a new detector

1. Create `src/dataforge/detectors/<your_detector>.py`
2. Implement `detect_<thing>(client, ...) -> Optional[Finding]`
3. Register it in `DataForgeAgent._scan_model()` (agent.py)
4. Add a sample incident to `examples/sample_incidents.json`
5. Add a unit test in `tests/detectors/test_<your_detector>.py`

## Adding a new model adapter

Model adapters expose feature extractors that the distribution-shift detector can sample. See `src/dataforge/adapters/critmin.py` for the reference implementation.

1. Create `src/dataforge/adapters/<your_model>.py`
2. Export a list of `Feature` dataclasses with `.feature_id` and `.extractor`
3. Wire it into `DataForgeAgent._scan_model()` (replace the CritMin-specific block with a registry lookup)

## Reporting issues

Please use the GitHub issue tracker. Include:
- DataHub version (`datahub version`)
- DataForge AI version (`python -c "import dataforge; print(dataforge.__version__)"`)
- Repro steps + expected vs. actual behavior
- Logs (set `LOG_LEVEL=DEBUG`)

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
