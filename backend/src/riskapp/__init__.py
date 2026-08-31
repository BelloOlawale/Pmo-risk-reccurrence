"""PMO Risk Recurrence Predictor — backend package."""

from riskapp.celery_app import celery_app

# Expose the Celery app under the conventional name so `celery -A riskapp`
# discovers it (Celery looks for an `app`/`celery` attribute on the package).
celery = celery_app

__all__ = ["celery", "celery_app"]
