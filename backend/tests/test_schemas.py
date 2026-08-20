"""Pydantic schema validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from riskapp import schemas


def test_project_create_requires_name() -> None:
    with pytest.raises(ValidationError):
        schemas.ProjectCreate.model_validate({"department": "D", "project_type": "T"})


def test_risk_create_rejects_invalid_likelihood() -> None:
    with pytest.raises(ValidationError):
        schemas.RiskCreate.model_validate(
            {"project_id": 1, "description": "x", "likelihood": "Critical", "impact": "High"}
        )


def test_risk_create_rejects_invalid_risk_source() -> None:
    with pytest.raises(ValidationError):
        schemas.RiskCreate.model_validate(
            {
                "project_id": 1,
                "description": "x",
                "likelihood": "High",
                "impact": "Medium",
                "risk_source": "Financial",
            }
        )


def test_risk_create_accepts_valid() -> None:
    risk = schemas.RiskCreate(
        project_id=1,
        description="Delay in AWS provisioning",
        likelihood="High",
        impact="Medium",
        risk_source="Technical",
        response_strategy="Mitigate",
    )
    assert risk.likelihood == "High"
    assert risk.risk_source == "Technical"
