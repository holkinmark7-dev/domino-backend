"""
test_clinical_engine_snapshot_v1.py — Clinical Engine v1.0.0 Snapshot Tests

Freezes the exact output of 5 key triage scenarios.
Any future change that breaks these assertions requires a version bump in
clinical_engine.py (CLINICAL_ENGINE_VERSION) and a new snapshot baseline.

Scenarios:
  S2  — GI diarrhea, last_hour=3  → CRITICAL / initial
  S4  — Juvenile 0.3y + mild lethargy → CRITICAL / initial
  S7  — Vomiting + refusing_water  → CRITICAL / initial
  S11 — Monotonic lock (previous HIGH, current MODERATE) → HIGH / improving
  S12 — Multi-layer senior 11y    → CRITICAL / initial

No Supabase / HTTP calls.  simulate_triage() from test_clinical_stress_matrix
is re-imported to keep this file lean.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.services.clinical_engine import CLINICAL_ENGINE_VERSION
from routers.services.chat_helpers import compute_episode_phase_v1

# Re-use the deterministic simulate_triage helper from the stress matrix
from tests.test_clinical_stress_matrix import simulate_triage


# ─────────────────────────────────────────────────────────────────────────────
# Helper: compute phase from a simulate_triage result
# ─────────────────────────────────────────────────────────────────────────────

def _phase(result: dict, previous_urgency_score: int | None = None) -> str:
    """
    Derive episode_phase from a simulate_triage result dict.
    previous_urgency_score mirrors the argument passed to simulate_triage.
    """
    from routers.services.risk_engine import ESCALATION_ORDER
    current_escalation = result["final_escalation"]
    previous_max_urgency = previous_urgency_score  # None or int 0-3
    monotonic_corrected = result["monotonic_corrected"]
    systemic_adjusted = result["systemic_adjusted"]
    cross_class_override = result["cross_class_override"]
    return compute_episode_phase_v1(
        current_escalation=current_escalation,
        previous_max_urgency=previous_max_urgency,
        monotonic_corrected=monotonic_corrected,
        systemic_adjusted=systemic_adjusted,
        cross_class_override=cross_class_override,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Version guard
# ─────────────────────────────────────────────────────────────────────────────

class TestVersionTag(unittest.TestCase):

    def test_version_is_frozen(self):
        """CLINICAL_ENGINE_VERSION must equal the frozen tag."""
        self.assertEqual(CLINICAL_ENGINE_VERSION, "v1.0.0-FROZEN")


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot tests
# ─────────────────────────────────────────────────────────────────────────────

class TestClinicalEngineSnapshotV1(unittest.TestCase):

    # ── S2: GI diarrhea, last_hour=3 → CRITICAL / initial ──────────────────
    def test_s2_snapshot(self):
        """
        3 diarrhea episodes in last hour → CLINICAL_RULES critical_last_hour=3
        → CRITICAL at Layer 1.  No prior events → episode_phase = initial.
        """
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 3, "last_hour": 3, "last_24h": 3},
            species="dog",
            age_years=3.0,
        )
        assert result["final_escalation"] == "CRITICAL", (
            f"S2 escalation changed: expected CRITICAL, got {result['final_escalation']}"
        )
        phase = _phase(result, previous_urgency_score=None)
        assert phase == "initial", (
            f"S2 phase changed: expected initial, got {phase}"
        )

    # ── S4: Juvenile 0.3y diarrhea + mild lethargy → CRITICAL / initial ────
    def test_s4_snapshot(self):
        """
        Juvenile (<0.5y) + GI + mild lethargy → CRITICAL via juvenile override.
        No prior events → episode_phase = initial.
        """
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            lethargy_level="mild",
            species="dog",
            age_years=0.3,
        )
        assert result["final_escalation"] == "CRITICAL", (
            f"S4 escalation changed: expected CRITICAL, got {result['final_escalation']}"
        )
        assert result["juvenile_adjusted"] is True, (
            f"S4 juvenile_adjusted changed: expected True"
        )
        phase = _phase(result, previous_urgency_score=None)
        assert phase == "initial", (
            f"S4 phase changed: expected initial, got {phase}"
        )

    # ── S7: Vomiting + refusing_water → CRITICAL / initial ─────────────────
    def test_s7_snapshot(self):
        """
        Vomiting (LOW from GI routing) + refusing_water
        → Systemic State GI+refusing_water rule → CRITICAL.
        No prior events → episode_phase = initial.
        """
        result = simulate_triage(
            symptom_key="vomiting",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            refusing_water=True,
            species="dog",
            age_years=5.0,
        )
        assert result["final_escalation"] == "CRITICAL", (
            f"S7 escalation changed: expected CRITICAL, got {result['final_escalation']}"
        )
        assert result["systemic_adjusted"] is True, (
            f"S7 systemic_adjusted changed: expected True"
        )
        phase = _phase(result, previous_urgency_score=None)
        assert phase == "initial", (
            f"S7 phase changed: expected initial, got {phase}"
        )

    # ── S11: Monotonic lock — previous HIGH, current MODERATE → HIGH / improving
    def test_s11_snapshot(self):
        """
        Previous episode urgency=2 (HIGH).  Current triage resolves MODERATE.
        Monotonic lock raises to HIGH.
        episode_phase = improving (monotonic_corrected=True).
        """
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 2, "last_hour": 1, "last_24h": 2},
            species="dog",
            age_years=3.0,
            previous_urgency_score=2,
            episode_id="ep-snapshot-s11",
        )
        assert result["final_escalation"] == "HIGH", (
            f"S11 escalation changed: expected HIGH, got {result['final_escalation']}"
        )
        assert result["monotonic_corrected"] is True, (
            f"S11 monotonic_corrected changed: expected True"
        )
        phase = _phase(result, previous_urgency_score=2)
        assert phase == "improving", (
            f"S11 phase changed: expected improving, got {phase}"
        )

    # ── S12: Multi-layer senior 11y → CRITICAL / initial ───────────────────
    def test_s12_snapshot(self):
        """
        Senior 11y, vomiting, mild lethargy, temp 39.8, recurrence:
          LOW → +mild lethargy → MODERATE (systemic)
          → temp 39.8 + lethargy → HIGH (systemic)
          → senior + systemic_adjusted → CRITICAL (age)
        No prior events → episode_phase = initial.
        """
        result = simulate_triage(
            symptom_key="vomiting",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            lethargy_level="mild",
            temperature_value=39.8,
            species="dog",
            age_years=11.0,
            episode_duration_hours=20.0,
            recurrent=True,
        )
        assert result["final_escalation"] == "CRITICAL", (
            f"S12 escalation changed: expected CRITICAL, got {result['final_escalation']}"
        )
        assert result["systemic_adjusted"] is True, (
            f"S12 systemic_adjusted changed: expected True"
        )
        assert result["age_adjusted"] is True, (
            f"S12 age_adjusted changed: expected True"
        )
        phase = _phase(result, previous_urgency_score=None)
        assert phase == "initial", (
            f"S12 phase changed: expected initial, got {phase}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestVersionTag))
    suite.addTests(loader.loadTestsFromTestCase(TestClinicalEngineSnapshotV1))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
