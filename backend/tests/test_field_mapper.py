"""Tests for the field mapper — map Excel columns → canonical fields."""

from __future__ import annotations

from riskapp.import_pipeline.field_mapper import (
    compute_rating,
    map_hml_to_full,
    map_numeric_to_level,
    map_punuka_row,
    map_seamless_hr_row,
    map_tnl_row,
    map_wacl_row,
    normalize_level,
)


class TestMapHmlToFull:
    def test_h_maps_to_high(self) -> None:
        assert map_hml_to_full("H") == "High"

    def test_m_maps_to_medium(self) -> None:
        assert map_hml_to_full("M") == "Medium"

    def test_l_maps_to_low(self) -> None:
        assert map_hml_to_full("L") == "Low"

    def test_already_full_word_passes_through(self) -> None:
        assert map_hml_to_full("High") == "High"
        assert map_hml_to_full("Medium") == "Medium"
        assert map_hml_to_full("low") == "Low"

    def test_empty_returns_empty(self) -> None:
        assert map_hml_to_full("") == ""
        assert map_hml_to_full("  ") == ""


class TestMapNumericToLevel:
    def test_1_2_map_to_low(self) -> None:
        assert map_numeric_to_level("1") == "Low"
        assert map_numeric_to_level("2") == "Low"

    def test_3_maps_to_medium(self) -> None:
        assert map_numeric_to_level("3") == "Medium"

    def test_4_5_map_to_high(self) -> None:
        assert map_numeric_to_level("4") == "High"
        assert map_numeric_to_level("5") == "High"

    def test_empty_returns_empty(self) -> None:
        assert map_numeric_to_level("") == ""
        assert map_numeric_to_level("TBD") == ""


class TestNormalizeLevel:
    def test_valid_levels_pass_through(self) -> None:
        assert normalize_level("High") == "High"
        assert normalize_level(" medium ") == "Medium"
        assert normalize_level("LOW") == "Low"

    def test_unknown_defaults_to_medium(self) -> None:
        assert normalize_level("") == "Medium"
        assert normalize_level("TBD") == "Medium"
        assert normalize_level("Critical") == "Medium"


class TestComputeRating:
    def test_matrix(self) -> None:
        assert compute_rating("High", "High") == "High"
        assert compute_rating("High", "Low") == "Medium"
        assert compute_rating("Low", "Low") == "Low"

    def test_unknown_inputs_default_to_medium(self) -> None:
        assert compute_rating("", "") == "Medium"


class TestMapPunukaRow:
    def test_maps_all_fields(self) -> None:
        row = {
            "Risk ID": "R001",
            "Risk Description": "Delay in requirements",
            "Risk Category": "Schedule",
            "Likelihood": "High",
            "Impact": "High",
            "Mitigation Strategy": "Engage early",
            "Risk Owner": "Punuka",
        }
        result = map_punuka_row(
            row, "BUSINESS SOLUTIONS", "Business Process Automation", "punuka_bpa.xlsx"
        )

        assert result["risk_description"] == "Delay in requirements"
        assert result["risk_category"] == "Schedule"
        assert result["likelihood"] == "High"
        assert result["impact"] == "High"
        assert result["risk_rating"] == "High"
        assert result["response_strategy"] == "Engage early"
        assert result["risk_owner"] == "Punuka"
        assert result["source_risk_id"] == "R001"
        assert result["source_file_name"] == "punuka_bpa.xlsx"
        assert result["department"] == "BUSINESS SOLUTIONS"
        assert result["project_type"] == "Business Process Automation"

    def test_computes_rating_from_likelihood_impact(self) -> None:
        row = {
            "Risk ID": "R012",
            "Risk Description": "Lack of buy-in",
            "Risk Category": "Organizational",
            "Likelihood": "Low",
            "Impact": "High",
            "Mitigation Strategy": "Engage sponsors",
            "Risk Owner": "Wragby/Punuka",
        }
        result = map_punuka_row(row, "BS", "BPA", "test.xlsx")
        assert result["risk_rating"] == "Medium"  # Low × High = Medium


class TestMapWaclRow:
    def test_maps_all_fields(self) -> None:
        row = {
            "ID": "1",
            "Description of Risk": "Unavailability of resources",
            "Probability": "5",
            "Impact": "5",
            "Risk Score": "25",
            "Risk Reponse": "Make provision for replacements",
            "Risk Level": "High",
            "Risk owner": "WACL",
        }
        result = map_wacl_row(row, "BS", "BPA", "wacl_bpa.xlsx")

        assert result["risk_description"] == "Unavailability of resources"
        assert result["likelihood"] == "High"
        assert result["impact"] == "High"
        assert result["risk_rating"] == "High"
        assert result["response_plan"] == "Make provision for replacements"
        assert result["risk_owner"] == "WACL"
        assert result["source_risk_id"] == "1"

    def test_computes_rating_from_matrix_not_explicit_level(self) -> None:
        """risk_rating always follows the 3×3 matrix (SPEC §4), even when the
        source carries an explicit Risk Level column."""
        row = {
            "ID": "2",
            "Description of Risk": "Scope Creep",
            "Probability": "4",
            "Impact": "4",
            "Risk Score": "16",
            "Risk Level": "Medium",
        }
        result = map_wacl_row(row, "BS", "BPA", "test.xlsx")
        assert result["risk_rating"] == "High"  # 4×4 → High×High, not Risk Level


class TestMapTnlRow:
    def test_maps_hml_values(self) -> None:
        row = {
            "Risk Description": "Delay in requirements",
            "Probability (H/M/L)": "H",
            "Impact (H/M/L)": "H",
            "Impact On": "Schedule",
            "Owner": "TNL",
            "Mitigation Steps": "Rebaseline schedule",
        }
        result = map_tnl_row(row, "BS", "ERP Implementation", "tnl_erp.xlsx")

        assert result["likelihood"] == "High"
        assert result["impact"] == "High"
        assert result["risk_rating"] == "High"
        assert result["response_plan"] == "Rebaseline schedule"
        assert result["risk_owner"] == "TNL"

    def test_handles_low_values(self) -> None:
        row = {
            "Risk Description": "Scope creep",
            "Probability (H/M/L)": "L",
            "Impact (H/M/L)": "L",
            "Impact On": "Schedule",
            "Owner": "TNL/Wragby",
            "Mitigation Steps": "Change management",
        }
        result = map_tnl_row(row, "BS", "ERP", "test.xlsx")

        assert result["likelihood"] == "Low"
        assert result["impact"] == "Low"
        assert result["risk_rating"] == "Low"


class TestMapSeamlessHrRow:
    def test_maps_numeric_values(self) -> None:
        row = {
            "S/N": "1",
            "Risk Description": "Delayed Delivery",
            "Impact (1-5)": "5",
            "Probability (1-5)": "3",
            "Rating (P X I)": "15",
            "Owner": "Seamless HR",
            "Risk Response": "Shift commencement date",
        }
        result = map_seamless_hr_row(row, "BS", "AI Integration", "seamless_hr.xlsx")

        assert result["risk_description"] == "Delayed Delivery"
        assert result["impact"] == "High"
        assert result["likelihood"] == "Medium"
        assert result["risk_rating"] == "High"  # Medium × High
        assert result["risk_owner"] == "Seamless HR"
        assert result["response_strategy"] == "Shift commencement date"
        assert result["source_risk_id"] == "1"
