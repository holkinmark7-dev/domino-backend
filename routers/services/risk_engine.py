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
from .breed_risk_modifiers import apply_breed_modifiers
from .age_modifiers import apply_age_modifiers
from typing import Optional

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
    has_combo: bool,
    duration_hours: float = None,
    species: str = "dog",
    age_category: str = "adult",
    breed: Optional[str] = None,
    weight_kg: Optional[float] = None,
    age_years: Optional[float] = None,
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

    # Применяем временные пороги
    if symptom_key and duration_hours:
        calculated_escalation = apply_time_thresholds(
            symptom_key=symptom_key,
            current_escalation=calculated_escalation,
            duration_hours=duration_hours,
            species=species,
            age_category=age_category,
        )

    # Применяем модификаторы породы и веса
    if breed or weight_kg:
        _symptoms_for_breed = [symptom_key] if symptom_key else []
        calculated_escalation, breed_reason = apply_breed_modifiers(
            detected_symptoms=_symptoms_for_breed,
            current_escalation=calculated_escalation,
            breed=breed,
            weight_kg=weight_kg,
            species=species,
        )

    # Применяем возрастные модификаторы
    if age_years is not None:
        _symptoms_for_age = [symptom_key] if symptom_key else []
        calculated_escalation, age_reason = apply_age_modifiers(
            detected_symptoms=_symptoms_for_age,
            current_escalation=calculated_escalation,
            age_years=age_years,
            species=species,
        )

    return {
        "risk_score": risk_score,
        "calculated_escalation": calculated_escalation,
    }


def apply_time_thresholds(
    symptom_key: str,
    current_escalation: str,
    duration_hours: float,
    species: str = "dog",
    age_category: str = "adult"
) -> str:
    """
    Применяет временные пороги к escalation.
    Эскалация никогда не понижается — только повышается.

    Аргументы:
        symptom_key: нормализованный ключ симптома ("vomiting", "anorexia" и т.д.)
        current_escalation: текущий уровень ("LOW"/"MODERATE"/"HIGH"/"CRITICAL")
        duration_hours: сколько часов длится симптом (из extraction)
        species: "dog" или "cat"
        age_category: "puppy", "kitten", "adult", "senior"

    Возвращает: новый уровень escalation (>= current_escalation)
    """
    from .symptom_registry_v2 import SYMPTOM_REGISTRY, escalate_min

    # Если нет данных о времени — ничего не меняем
    if duration_hours is None or duration_hours <= 0:
        return current_escalation

    # Если симптом не в реестре — ничего не меняем
    symptom_data = SYMPTOM_REGISTRY.get(symptom_key)
    if not symptom_data:
        return current_escalation

    thresholds = symptom_data.get("time_thresholds", [])
    if not thresholds:
        return current_escalation

    result = current_escalation

    for threshold in thresholds:
        threshold_hours = threshold.get("hours", 0)
        threshold_species = threshold.get("species", "all")
        threshold_escalation = threshold.get("escalation", "LOW")

        # Проверяем подходит ли этот порог по виду/возрасту
        species_match = (
            threshold_species == "all"
            or threshold_species == species
            or threshold_species == age_category  # puppy, kitten
        )

        if not species_match:
            continue

        # Если время превышает порог — применяем escalation
        if duration_hours >= threshold_hours:
            result = escalate_min(result, threshold_escalation)

    return result
