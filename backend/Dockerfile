# Backend image for the PMO Risk Recurrence Predictor.
#
# One image, three entrypoints:
#   web    (default)  uvicorn riskapp.main:app
#   worker            celery -A riskapp.celery_app:celery_app worker --loglevel=INFO
#   beat              celery -A riskapp.celery_app:celery_app beat --loglevel=INFO
#
# Example overrides (Docker Compose / Container Apps):
#   command: ["celery", "-A", "riskapp.celery_app:celery_app", "worker", "--loglevel=INFO"]
#   command: ["celery", "-A", "riskapp.celery_app:celery_app", "beat", "--loglevel=INFO"]

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the application package. Dependencies come from pyproject.toml and
# are all available as wheels, so no compiler toolchain is needed.
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

# Alembic assets live outside the Python package, so copy them explicitly so
# "alembic upgrade head" can run from inside the container at deploy time.
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

CMD ["uvicorn", "riskapp.main:app", "--host", "0.0.0.0", "--port", "8000"]
