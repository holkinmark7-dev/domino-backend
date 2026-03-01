"""
RISK ENGINE v1 — BASELINE (FROZEN)

Score → Escalation mapping:

0–1  → LOW
2–3  → MODERATE
4–5  → HIGH
6+   → CRITICAL

Rules:
- Risk engine runs in shadow mode.
- decision["escalation"] remains source of truth.
- calculated_escalation must never be lower than old_escalation (guard in chat.py).
- This mapping is frozen for v1 and must not change without full regression matrix.
"""

from .symptom_registry_v2 import SYMPTOM_REGISTRY, escalate_min, ESCALATION_ORDER as _V2_ESCALATION_ORDER
from .combo_matrix import apply_combo_matrix

ESCALATION_ORDER = {
    "LOW": 0,
    "MODERATE": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


def map_score_to_escalation(score: int) -> str:
    if score <= 1:
        return "LOW"
    elif score <= 3:
        return "MODERATE"
    elif score <= 5:
        return "HIGH"
    else:
        return "CRITICAL"


def calculate_risk_score(
    symptom_key: str,
    stats: dict,
    blood: bool,
    episode_phase: str,
    has_combo: bool
) -> dict:
    risk_score = 0

    # Base symptom
    if symptom_key in ["vomiting", "diarrhea"]:
        risk_score += 1

    # Blood factor
    if blood:
        risk_score += 3

    # Frequency last hour
    if stats.get("last_hour", 0) >= 3:
        risk_score += 4

    # Frequency today
    elif stats.get("today", 0) >= 3:
        risk_score += 2

    # Cross symptom combo
    if has_combo:
        risk_score += 2

    # Recurrence
    if episode_phase == "progressing":
        risk_score += 1

    # Escalation mapping
    calculated_escalation = map_score_to_escalation(risk_score)

    # Применяем комбо-матрицу для учёта опасных комбинаций симптомов
    detected_symptoms = [symptom_key] if symptom_key else []
    if detected_symptoms and len(detected_symptoms) > 1:
        final_escalation, combo_reason = apply_combo_matrix(
            detected_symptoms=detected_symptoms,
            current_escalation=calculated_escalation,
            species="dog"
        )
        if combo_reason:
            calculated_escalation = final_escalation

    return {
        "risk_score": risk_score,
        "calculated_escalation": calculated_escalation,
    }
