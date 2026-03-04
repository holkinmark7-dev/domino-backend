"""
Part A — Boundary value tests for the triage engine.

Tests exercise calculate_risk_score (pure logic, no DB),
apply_time_thresholds, build_clinical_decision, and evaluate_clinical_escalation.
"""
import sys
import os
import pytest
from freezegun import freeze_time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.services.risk_engine import (
    calculate_risk_score,
    apply_time_thresholds,
    map_score_to_escalation,
    ESCALATION_ORDER,
)
from routers.services.clinical_engine import (
    build_clinical_decision,
    evaluate_clinical_escalation,
)


def _esc_index(level: str) -> int:
    return ESCALATION_ORDER.get(level, 0)


# ══════════════════════════════════════════════════════════════════════════════
# calculate_risk_score — base score + modifiers
# ══════════════════════════════════════════════════════════════════════════════
class TestRiskScoreBaseline:

    def test_vomiting_zero_stats_low(self):
        """Vomiting with zero stats → LOW (base score 1)."""
        r = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 0, "last_hour": 0, "last_24h": 0},
            blood=False, episode_phase="initial", has_combo=False,
        )
        assert r["calculated_escalation"] == "LOW"

    def test_blood_raises_score(self):
        """Blood adds +3, pushes past LOW."""
        r = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 0, "last_hour": 0, "last_24h": 0},
            blood=True, episode_phase="initial", has_combo=False,
        )
        assert _esc_index(r["calculated_escalation"]) >= _esc_index("HIGH")

    def test_high_frequency_last_hour_critical(self):
        """3+ events last hour → score jumps significantly."""
        r = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 5, "last_hour": 3, "last_24h": 5},
            blood=False, episode_phase="initial", has_combo=False,
        )
        assert _esc_index(r["calculated_escalation"]) >= _esc_index("HIGH")

    def test_combo_adds_score(self):
        """has_combo=True adds +2."""
        without = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 1, "last_hour": 0, "last_24h": 1},
            blood=False, episode_phase="initial", has_combo=False,
        )
        with_combo = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 1, "last_hour": 0, "last_24h": 1},
            blood=False, episode_phase="initial", has_combo=True,
        )
        assert with_combo["risk_score"] > without["risk_score"]

    def test_progressing_phase_adds_score(self):
        """episode_phase='progressing' adds +1."""
        normal = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 1, "last_hour": 0, "last_24h": 1},
            blood=False, episode_phase="initial", has_combo=False,
        )
        prog = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 1, "last_hour": 0, "last_24h": 1},
            blood=False, episode_phase="progressing", has_combo=False,
        )
        assert prog["risk_score"] > normal["risk_score"]


# ══════════════════════════════════════════════════════════════════════════════
# apply_time_thresholds — duration escalation
# ══════════════════════════════════════════════════════════════════════════════
class TestTimeDurationBoundary:

    def test_zero_duration_no_change(self):
        """duration_hours=0 → no escalation change."""
        result = apply_time_thresholds("vomiting", "LOW", 0.0)
        assert result == "LOW"

    def test_none_duration_no_change(self):
        """duration_hours=None → no escalation change."""
        result = apply_time_thresholds("vomiting", "LOW", None)
        assert result == "LOW"

    def test_short_duration_no_escalation(self):
        """1 hour of vomiting → stays LOW for adult dog."""
        result = apply_time_thresholds("vomiting", "LOW", 1.0, species="dog")
        assert result == "LOW"

    def test_12h_vomiting_dog_escalates(self):
        """12h of vomiting in dog → should escalate above LOW."""
        result = apply_time_thresholds("vomiting", "LOW", 12.0, species="dog")
        assert _esc_index(result) >= _esc_index("MODERATE")

    def test_24h_vomiting_dog_high_or_above(self):
        """24h of vomiting in dog → HIGH or above."""
        result = apply_time_thresholds("vomiting", "LOW", 24.0, species="dog")
        assert _esc_index(result) >= _esc_index("HIGH")

    def test_never_lowers_escalation(self):
        """Time thresholds never lower existing escalation."""
        result = apply_time_thresholds("vomiting", "HIGH", 0.5, species="dog")
        assert _esc_index(result) >= _esc_index("HIGH")

    def test_unknown_symptom_no_change(self):
        """Unknown symptom not in registry → no escalation change."""
        result = apply_time_thresholds("alien_flu", "LOW", 48.0)
        assert result == "LOW"


# ══════════════════════════════════════════════════════════════════════════════
# Age modifiers via calculate_risk_score
# ══════════════════════════════════════════════════════════════════════════════
class TestAgeModifiers:

    def test_puppy_0_5_gets_higher_or_equal(self):
        """Young puppy (0.5y) → escalation >= adult (3y)."""
        young = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 2, "last_hour": 0, "last_24h": 2},
            blood=False, episode_phase="initial", has_combo=False,
            age_years=0.5,
        )
        adult = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 2, "last_hour": 0, "last_24h": 2},
            blood=False, episode_phase="initial", has_combo=False,
            age_years=3.0,
        )
        assert _esc_index(young["calculated_escalation"]) >= _esc_index(adult["calculated_escalation"])

    def test_very_young_0_2_no_crash(self):
        """Very young animal (0.2y) → handled without error."""
        r = calculate_risk_score(
            symptom_key="diarrhea",
            stats={"today": 1, "last_hour": 0, "last_24h": 1},
            blood=False, episode_phase="initial", has_combo=False,
            age_years=0.2, species="cat",
        )
        assert r["calculated_escalation"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")

    def test_senior_15_no_crash(self):
        """Very old animal (15y) → handled without error."""
        r = calculate_risk_score(
            symptom_key="vomiting",
            stats={"today": 1, "last_hour": 0, "last_24h": 1},
            blood=False, episode_phase="initial", has_combo=False,
            age_years=15.0, species="cat",
        )
        assert r["calculated_escalation"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")


# ══════════════════════════════════════════════════════════════════════════════
# evaluate_clinical_escalation — pure rules
# ══════════════════════════════════════════════════════════════════════════════
class TestClinicalEscalation:

    def test_vomiting_zero_stats_low(self):
        """No events → LOW."""
        r = evaluate_clinical_escalation("vomiting", {"today": 0, "last_hour": 0, "last_24h": 0})
        assert r == "LOW"

    def test_vomiting_3_today_moderate(self):
        """3 today → MODERATE per clinical rules."""
        r = evaluate_clinical_escalation("vomiting", {"today": 3, "last_hour": 0, "last_24h": 3})
        assert _esc_index(r) >= _esc_index("MODERATE")

    def test_vomiting_3_last_hour_critical(self):
        """3 in last hour → CRITICAL."""
        r = evaluate_clinical_escalation("vomiting", {"today": 3, "last_hour": 3, "last_24h": 3})
        assert r == "CRITICAL"

    def test_unknown_symptom_low(self):
        """Unknown symptom not in CLINICAL_RULES → LOW."""
        r = evaluate_clinical_escalation("unknown_xyz", {"today": 10, "last_hour": 5, "last_24h": 10})
        assert r == "LOW"


# ══════════════════════════════════════════════════════════════════════════════
# map_score_to_escalation — boundary values
# ══════════════════════════════════════════════════════════════════════════════
class TestScoreMapping:

    def test_score_0_low(self):
        assert map_score_to_escalation(0) == "LOW"

    def test_score_1_low(self):
        assert map_score_to_escalation(1) == "LOW"

    def test_score_2_moderate(self):
        assert map_score_to_escalation(2) == "MODERATE"

    def test_score_3_moderate(self):
        assert map_score_to_escalation(3) == "MODERATE"

    def test_score_4_high(self):
        assert map_score_to_escalation(4) == "HIGH"

    def test_score_5_high(self):
        assert map_score_to_escalation(5) == "HIGH"

    def test_score_6_critical(self):
        assert map_score_to_escalation(6) == "CRITICAL"

    def test_score_99_critical(self):
        assert map_score_to_escalation(99) == "CRITICAL"
