# PMO Risk Recurrence Predictor — App

Standalone web application merging the FRD and the PMO Risk Management Document.
See `SPEC.md` for the authoritative build spec.

## Structure

```
backend/   Python + FastAPI (this is where we start)
frontend/  React + TypeScript (added later)
```

## Backend quickstart

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pytest
```

## Development conventions

- TDD: write tests first, then implement.
- `src/riskapp/domain/` holds pure, side-effect-free logic (no DB, no HTTP).
- Feedback loops before committing: `pytest`, `ruff check .`, `mypy .`
