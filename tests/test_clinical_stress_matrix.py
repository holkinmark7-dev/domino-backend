"""
test_clinical_stress_matrix.py — DAY 3.2 Clinical Stress Test Matrix

12 deterministic scenarios exercising the full multi-layer triage pipeline.
No Supabase / HTTP calls.  All DB dependencies are stubbed via simulate_triage().

Per-test output:  final_escalation | monotonic_corrected | systemic_adjusted
                  age_adjusted | episode_adjusted | cross_class_override

Layer order mirrors routers/chat.py:
  1.  Clinical routing  (GI / RESPIRATORY / NEURO / INGESTION / TOXIC / URINARY)
  2.  Blood Type Override
  3.  GDV Override
  4.  Absolute Critical & Vital Signs
  5.  Systemic State  (lethargy, temp, refusing_water, temp+lethargy)
  6.  Species & Age Multipliers
  7.  Episode Clinical  (duration, recurrence)
  8.  Cat Anorexia Override
  9.  Cross-Class Override
 10.  Monotonic Lock
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routers.services.clinical_engine import build_clinical_decision
from routers.services.risk_engine import ESCALATION_ORDER
from routers.services.chat_helpers import escalate_min, apply_monotonic_lock


# ─────────────────────────────────────────────────────────────────────────────
# simulate_triage() — deterministic multi-layer engine (no Supabase)
# ─────────────────────────────────────────────────────────────────────────────

def simulate_triage(
    symptom_key: str,
    symptom_class: str,
    stats: dict,                    # {today, last_hour, last_24h}
    *,
    lethargy_level: str = "none",   # "none" | "mild" | "severe"
    temperature_value: float | None = None,
    respiratory_rate: int | None = None,
    seizure_duration: float | None = None,
    refusing_water: bool = False,
    species: str = "dog",           # "dog" | "cat"
    age_years: float | None = None,
    episode_duration_hours: float | None = None,
    recurrent: bool = False,
    # cross-class signals
    has_combo_vomit_diarrhea: bool = False,  # vomiting + diarrhea in 24h window
    has_seizure_signal: bool = False,
    has_vomiting_signal: bool = False,
    has_collapse_signal: bool = False,
    # monotonic lock
    previous_urgency_score: int | None = None,  # prior episode max (0-3 int)
    episode_id: str | None = "ep-test-001",
) -> dict:
    """
    Pure-Python mirror of the route-handler layer order.
    Returns a debug dict matching the shape produced by chat.py.
    """

    decision: dict | None = None
    _respiratory_recalibrated = False
    _systemic_adjusted = False
    _age_adjusted = False
    _juvenile_adjusted = False
    _episode_adjusted = False
    _cross_class_override = False
    _temp_lethargy_override = False

    # ── 1. Clinical routing ───────────────────────────────────────────────────
    if symptom_class == "GI":
        decision = build_clinical_decision(symptom_key, stats)

        # cross-symptom (vomiting + diarrhea combo within 24h → min HIGH)
        if has_combo_vomit_diarrhea:
            if decision["escalation"] in ["LOW", "MODERATE"]:
                decision["escalation"] = "HIGH"

    elif symptom_class == "RESPIRATORY":
        if symptom_key == "difficulty_breathing" and lethargy_level != "none":
            _esc = "CRITICAL"
            _respiratory_recalibrated = True
        elif symptom_key == "difficulty_breathing":
            _esc = "HIGH"
        elif lethargy_level != "none":
            _esc = "MODERATE"
            _respiratory_recalibrated = True
        elif stats.get("today", 0) >= 2:
            _esc = "MODERATE"
            _respiratory_recalibrated = True
        else:
            _esc = "LOW"

        decision = {
            "escalation": _esc,
            "stats": stats,
            "symptom": symptom_key,
            "stop_questioning": _esc in ["HIGH", "CRITICAL"],
            "override_urgency": _esc in ["HIGH", "CRITICAL"],
        }

    elif symptom_class == "NEURO":
        if stats.get("last_24h", 0) >= 2:
            _esc = "CRITICAL"
        elif isinstance(seizure_duration, float) and seizure_duration >= 2.0:
            _esc = "CRITICAL"
        elif isinstance(seizure_duration, float) and seizure_duration < 1.0:
            _esc = "HIGH"
        else:
            _esc = "HIGH"

        decision = {
            "escalation": _esc,
            "stats": stats,
            "symptom": symptom_key,
            "stop_questioning": True,
            "override_urgency": True,
        }

    elif symptom_class == "INGESTION":
        _esc = "CRITICAL" if symptom_key in ["choking", "bone_stuck"] else "HIGH"
        decision = {
            "escalation": _esc,
            "stats": stats,
            "symptom": symptom_key,
            "stop_questioning": True,
            "override_urgency": True,
            "ingestion_adjusted": True,
        }

    elif symptom_class == "TOXIC":
        if symptom_key == "xylitol_toxicity":
            _esc = "CRITICAL"
        elif symptom_key == "antifreeze":
            _esc = "CRITICAL"
        elif symptom_key == "rodenticide":
            _esc = "HIGH"
        else:
            _esc = "HIGH"
        decision = {
            "escalation": _esc,
            "stats": stats,
            "symptom": symptom_key,
            "stop_questioning": True,
            "override_urgency": True,
        }

    elif symptom_class == "URINARY":
        if species == "cat":
            _esc = "CRITICAL" if lethargy_level != "none" else "MODERATE"
        else:
            _esc = "HIGH" if lethargy_level != "none" else "MODERATE"
        decision = {
            "escalation": _esc,
            "stats": stats,
            "symptom": symptom_key,
            "stop_questioning": _esc in ["HIGH", "CRITICAL"],
            "override_urgency": _esc in ["HIGH", "CRITICAL"],
        }

    # ── 4. Absolute Critical & Vital Signs Layer ──────────────────────────────
    if decision and isinstance(temperature_value, float):
        # temp ≥ 41 → CRITICAL
        if temperature_value >= 41.0:
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")

        # temp ≥ 40 + severe lethargy → CRITICAL
        if temperature_value >= 40.0 and lethargy_level == "severe":
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")

    # Respiratory rate
    if decision and isinstance(respiratory_rate, int):
        if respiratory_rate >= 50:
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        elif respiratory_rate >= 40:
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")

    # ── 5. Systemic State Layer ───────────────────────────────────────────────
    if decision:
        # Skip lethargy for RESPIRATORY (baked in)
        _is_respiratory = symptom_class == "RESPIRATORY"
        if not _is_respiratory:
            if lethargy_level == "mild":
                _cur = decision["escalation"]
                _idx = ESCALATION_ORDER[_cur]
                _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
                if _new != _cur:
                    decision["escalation"] = _new
                    _systemic_adjusted = True

            elif lethargy_level == "severe":
                _before = decision["escalation"]
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                if decision["escalation"] != _before:
                    _systemic_adjusted = True

        # GI + refusing_water → CRITICAL
        if refusing_water and symptom_class == "GI":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # GI + severe lethargy → CRITICAL
        if lethargy_level == "severe" and symptom_class == "GI":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # refusing_water + lethargy → min HIGH
        if refusing_water and lethargy_level != "none":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # refusing_water + lethargy + GI → CRITICAL
        if refusing_water and lethargy_level != "none" and symptom_class == "GI":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # Temperature escalation (v4.4)
        if isinstance(temperature_value, float):
            _before = decision["escalation"]
            if temperature_value >= 40.0:
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                _systemic_adjusted = True
            elif temperature_value >= 39.7:
                decision["escalation"] = escalate_min(decision["escalation"], "MODERATE")
                if decision["escalation"] != _before:
                    _systemic_adjusted = True

        # Temp + any lethargy combined (v4.4)
        if isinstance(temperature_value, float) and lethargy_level != "none":
            if temperature_value >= 40.0:
                decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                _systemic_adjusted = True
                _temp_lethargy_override = True
            elif temperature_value >= 39.7:
                _before = decision["escalation"]
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                if decision["escalation"] != _before:
                    _systemic_adjusted = True
                _temp_lethargy_override = True

        decision["systemic_adjusted"] = _systemic_adjusted

    # ── 6. Species & Age Multipliers ─────────────────────────────────────────
    if decision:
        # Cat + RESPIRATORY → min HIGH
        if species == "cat" and symptom_class == "RESPIRATORY":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            if decision["escalation"] != _before:
                _species_adjusted = True

        # Cat + difficulty_breathing + lethargy → CRITICAL
        if species == "cat" and symptom_key == "difficulty_breathing" and lethargy_level != "none":
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")

        # Puppy/kitten (age < 1y) + GI → +1
        if (
            isinstance(age_years, float)
            and age_years < 1
            and symptom_class == "GI"
        ):
            _cur = decision["escalation"]
            _idx = ESCALATION_ORDER[_cur]
            _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
            if _new != _cur:
                decision["escalation"] = _new
                _age_adjusted = True

        # Juvenile (age < 0.5y) + GI + lethargy or refusing_water → CRITICAL
        if (
            isinstance(age_years, float)
            and age_years < 0.5
            and symptom_class == "GI"
            and (lethargy_level != "none" or refusing_water)
        ):
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _juvenile_adjusted = True

        # Senior (age >= 10) + systemic_adjusted → +1
        if (
            isinstance(age_years, float)
            and age_years >= 10
            and decision.get("systemic_adjusted")
        ):
            _cur = decision["escalation"]
            _idx = ESCALATION_ORDER[_cur]
            _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
            if _new != _cur:
                decision["escalation"] = _new
                _age_adjusted = True

        decision["age_adjusted"] = _age_adjusted
        decision["juvenile_adjusted"] = _juvenile_adjusted

    # ── 7. Episode Clinical Layer ─────────────────────────────────────────────
    if decision and episode_duration_hours is not None:
        # GI duration (species-aware)
        if symptom_class == "GI":
            if isinstance(age_years, float) and age_years < 0.5:
                if episode_duration_hours >= 6:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        _episode_adjusted = True
            elif species == "cat":
                if episode_duration_hours >= 12:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        _episode_adjusted = True
            else:  # adult dog
                if episode_duration_hours >= 24:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        _episode_adjusted = True
                elif episode_duration_hours >= 12:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "MODERATE")
                    if decision["escalation"] != _before:
                        _episode_adjusted = True

        # Recurrence → +1 if not already CRITICAL
        if recurrent and decision["escalation"] != "CRITICAL":
            _cur = decision["escalation"]
            _idx = ESCALATION_ORDER[_cur]
            _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
            if _new != _cur:
                decision["escalation"] = _new
                _episode_adjusted = True

        decision["episode_adjusted"] = _episode_adjusted
    else:
        if decision:
            decision["episode_adjusted"] = False

    # ── 9. Cross-Class Override Layer ─────────────────────────────────────────
    if decision:
        if has_seizure_signal and has_vomiting_signal:
            decision["escalation"] = "CRITICAL"
            _cross_class_override = True

        if has_collapse_signal:
            decision["escalation"] = "CRITICAL"
            _cross_class_override = True

        decision["cross_class_override"] = _cross_class_override

    # ── 10. Monotonic Lock ────────────────────────────────────────────────────
    _monotonic_corrected = False
    if decision and previous_urgency_score is not None and episode_id:
        fake_events = [
            {
                "content": {
                    "episode_id": episode_id,
                    "urgency_score": previous_urgency_score,
                }
            }
        ]
        apply_monotonic_lock(decision, episode_id, fake_events)
        _monotonic_corrected = decision.get("monotonic_corrected", False)
    else:
        if decision:
            decision["monotonic_corrected"] = False

    return {
        "final_escalation": decision["escalation"] if decision else "NONE",
        "monotonic_corrected": decision.get("monotonic_corrected", False) if decision else False,
        "systemic_adjusted": decision.get("systemic_adjusted", False) if decision else False,
        "age_adjusted": decision.get("age_adjusted", False) if decision else False,
        "juvenile_adjusted": decision.get("juvenile_adjusted", False) if decision else False,
        "episode_adjusted": decision.get("episode_adjusted", False) if decision else False,
        "cross_class_override": decision.get("cross_class_override", False) if decision else False,
        "_decision": decision,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_result(scenario: str, result: dict) -> None:
    print(
        f"\n  [{scenario}]"
        f"  escalation={result['final_escalation']}"
        f"  monotonic_corrected={result['monotonic_corrected']}"
        f"  systemic_adjusted={result['systemic_adjusted']}"
        f"  age_adjusted={result['age_adjusted']}"
        f"  episode_adjusted={result['episode_adjusted']}"
        f"  cross_class_override={result['cross_class_override']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test class
# ─────────────────────────────────────────────────────────────────────────────

class TestClinicalStressMatrix(unittest.TestCase):
    """
    12 clinical stress scenarios.  Each asserts final_escalation and at least
    one key debug flag.
    """

    # ── S1: Adult dog, mild diarrhea, 1 episode, no modifiers ──────────────
    def test_s1_adult_dog_mild_diarrhea(self):
        """Baseline: single diarrhea episode with no modifiers → LOW."""
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            species="dog",
            age_years=3.0,
        )
        _print_result("S1", result)
        self.assertEqual(result["final_escalation"], "LOW")
        self.assertFalse(result["systemic_adjusted"])
        self.assertFalse(result["age_adjusted"])

    # ── S2: Adult dog, 3 diarrhea episodes in last hour ────────────────────
    def test_s2_adult_dog_diarrhea_critical_last_hour(self):
        """CLINICAL_RULES critical_last_hour=3 → CRITICAL immediately."""
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 3, "last_hour": 3, "last_24h": 3},
            species="dog",
            age_years=3.0,
        )
        _print_result("S2", result)
        self.assertEqual(result["final_escalation"], "CRITICAL")
        self.assertFalse(result["systemic_adjusted"])

    # ── S3: Adult dog, diarrhea + mild lethargy ────────────────────────────
    def test_s3_adult_dog_diarrhea_mild_lethargy(self):
        """Single diarrhea (LOW) + mild lethargy → systemic +1 → MODERATE."""
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            lethargy_level="mild",
            species="dog",
            age_years=3.0,
        )
        _print_result("S3", result)
        self.assertEqual(result["final_escalation"], "MODERATE")
        self.assertTrue(result["systemic_adjusted"])
        self.assertFalse(result["age_adjusted"])

    # ── S4: Puppy <6m, diarrhea + mild lethargy → CRITICAL ────────────────
    def test_s4_puppy_diarrhea_lethargy_critical(self):
        """
        Juvenile (<0.5y) + GI + lethargy → CRITICAL via juvenile override.
        Route: LOW(GI) → MODERATE(+mild lethargy) → CRITICAL(juvenile).
        """
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            lethargy_level="mild",
            species="dog",
            age_years=0.3,    # 3.6 months
        )
        _print_result("S4", result)
        self.assertEqual(result["final_escalation"], "CRITICAL")
        self.assertTrue(result["juvenile_adjusted"])

    # ── S5: Cat, cough only, today=1 → HIGH (species RESPIRATORY floor) ───
    def test_s5_cat_cough_species_floor(self):
        """
        Cat + cough/sneezing alone → LOW from RESPIRATORY routing,
        then Species layer raises to HIGH (cat+RESPIRATORY min HIGH).
        """
        result = simulate_triage(
            symptom_key="cough",
            symptom_class="RESPIRATORY",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            species="cat",
            age_years=2.0,
        )
        _print_result("S5", result)
        self.assertEqual(result["final_escalation"], "HIGH")

    # ── S6: Cat, respiratory_rate=52 → CRITICAL ────────────────────────────
    def test_s6_cat_respiratory_rate_52_critical(self):
        """
        Cat, respiratory_rate ≥50 → CRITICAL (Absolute Critical / Vital Signs layer).
        Base routing: cough → LOW; after RR≥50: CRITICAL.
        """
        result = simulate_triage(
            symptom_key="cough",
            symptom_class="RESPIRATORY",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            respiratory_rate=52,
            species="cat",
            age_years=4.0,
        )
        _print_result("S6", result)
        self.assertEqual(result["final_escalation"], "CRITICAL")

    # ── S7: GI + refusing_water → CRITICAL ────────────────────────────────
    def test_s7_gi_refusing_water_critical(self):
        """
        Vomiting (LOW from GI routing) + refusing_water
        → Systemic State GI+refusing_water → CRITICAL.
        """
        result = simulate_triage(
            symptom_key="vomiting",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            refusing_water=True,
            species="dog",
            age_years=5.0,
        )
        _print_result("S7", result)
        self.assertEqual(result["final_escalation"], "CRITICAL")
        self.assertTrue(result["systemic_adjusted"])

    # ── S8: Vomiting + diarrhea combo (cross-symptom) within 24h → HIGH ───
    def test_s8_vomiting_diarrhea_combo_high(self):
        """
        Vomiting 1 episode (→ LOW from GI routing) +
        cross-symptom diarrhea within 24h → min HIGH via has_combo flag.
        """
        result = simulate_triage(
            symptom_key="vomiting",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            has_combo_vomit_diarrhea=True,
            species="dog",
            age_years=4.0,
        )
        _print_result("S8", result)
        self.assertEqual(result["final_escalation"], "HIGH")

    # ── S9: Single seizure <1 min → HIGH ──────────────────────────────────
    def test_s9_seizure_short_duration_high(self):
        """
        Single seizure, duration=0.5 min (<1.0 threshold) → HIGH.
        No additional modifiers.
        """
        result = simulate_triage(
            symptom_key="seizure",
            symptom_class="NEURO",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            seizure_duration=0.5,
            species="dog",
            age_years=3.0,
        )
        _print_result("S9", result)
        self.assertEqual(result["final_escalation"], "HIGH")

    # ── S10: Seizure ≥2 min → CRITICAL ────────────────────────────────────
    def test_s10_seizure_long_duration_critical(self):
        """
        Seizure, duration=3.0 min (≥2.0 threshold) → CRITICAL.
        """
        result = simulate_triage(
            symptom_key="seizure",
            symptom_class="NEURO",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            seizure_duration=3.0,
            species="dog",
            age_years=3.0,
        )
        _print_result("S10", result)
        self.assertEqual(result["final_escalation"], "CRITICAL")

    # ── S11: Monotonic lock — previous HIGH, new MODERATE → HIGH ──────────
    def test_s11_monotonic_lock_holds_high(self):
        """
        Previous episode urgency=2 (HIGH).  Current triage resolves MODERATE.
        Monotonic lock must raise back to HIGH; monotonic_corrected=True.
        """
        result = simulate_triage(
            symptom_key="diarrhea",
            symptom_class="GI",
            stats={"today": 2, "last_hour": 1, "last_24h": 2},  # today=2 → MODERATE from CLINICAL_RULES
            species="dog",
            age_years=3.0,
            previous_urgency_score=2,   # previous HIGH
            episode_id="ep-monotonic-001",
        )
        _print_result("S11", result)
        self.assertEqual(result["final_escalation"], "HIGH")
        self.assertTrue(result["monotonic_corrected"])

    # ── S12: Multi-layer — GI + mild lethargy + temp 39.8 + senior ≥10y + recurrence → CRITICAL
    def test_s12_multi_layer_senior_dog_critical(self):
        """
        Adult dog ≥10y, vomiting 1 episode:
          - GI routing → LOW
          - mild lethargy → +1 → MODERATE  (systemic_adjusted=True)
          - temp 39.8 (≥39.7) → min MODERATE (already there, no change)
          - temp 39.8 + mild lethargy (≥39.7 + any lethargy) → min HIGH (systemic_adjusted=True)
          - senior ≥10y + systemic_adjusted → +1 → CRITICAL  (age_adjusted=True)
          - recurrence → +1 but already CRITICAL (no extra change; episode_adjusted=False from recurrence since already CRITICAL)
        """
        result = simulate_triage(
            symptom_key="vomiting",
            symptom_class="GI",
            stats={"today": 1, "last_hour": 1, "last_24h": 1},
            lethargy_level="mild",
            temperature_value=39.8,
            species="dog",
            age_years=11.0,
            episode_duration_hours=20.0,  # <24h so no GI duration uplift
            recurrent=True,
        )
        _print_result("S12", result)
        self.assertEqual(result["final_escalation"], "CRITICAL")
        self.assertTrue(result["systemic_adjusted"])
        self.assertTrue(result["age_adjusted"])


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestClinicalStressMatrix)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"\n{'-' * 60}")
    print(f"TOTAL: {passed}/{total} PASS")
