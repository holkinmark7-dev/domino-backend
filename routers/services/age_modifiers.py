# age_modifiers.py
# Модификаторы риска на основе возраста питомца
# Применяется ПОСЛЕ базового triage — только повышает escalation
# Логика по рекомендации ветеринара: не автоматически +1 ко всему,
# а только для специфических опасных комбинаций
# Python 3.9 compatible

from typing import Optional, List, Tuple

ESCALATION_ORDER = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def escalate_min(a: str, b: str) -> str:
    """Возвращает более высокий уровень из двух."""
    return a if ESCALATION_ORDER.index(a) >= ESCALATION_ORDER.index(b) else b


# Симптомы которые у пожилых кошек (>10 лет) требуют усиления
SENIOR_CAT_ESCALATIONS = {
    "anorexia": "HIGH",           # липидоз печени быстро развивается
    "lethargy": "MODERATE",       # у пожилой кошки вялость — сигнал
    "severe_lethargy": "HIGH",
    "weight_loss": "HIGH",        # опухоли, гипертиреоз
    "polyuria": "HIGH",           # ХПН
    "polydipsia": "HIGH",         # диабет, ХПН
    "vomiting": "MODERATE",       # ХПН, гипертиреоз
}

# Симптомы которые у пожилых собак (>9 лет) требуют усиления
SENIOR_DOG_ESCALATIONS = {
    "collapse": "CRITICAL",       # сердце, опухоль
    "syncope": "CRITICAL",        # аритмия
    "exercise_intolerance": "HIGH",
    "dyspnea": "HIGH",
    "severe_lethargy": "HIGH",
    "sudden_blindness": "HIGH",   # гипертония
}

# Симптомы которые у щенков/котят (< 6 месяцев) требуют усиления
PUPPY_KITTEN_ESCALATIONS = {
    "vomiting": "MODERATE",
    "diarrhea": "MODERATE",
    "lethargy": "MODERATE",
    "anorexia": "HIGH",           # гипогликемия быстрее
    "collapse": "CRITICAL",
    "severe_lethargy": "HIGH",
}


def compute_age_category(
    age_years: Optional[float],
    species: str = "dog"
) -> str:
    """
    Определяет возрастную категорию питомца.

    Возвращает: "puppy", "kitten", "adult", "senior_cat", "senior_dog"
    """
    if age_years is None:
        return "adult"

    if species == "cat":
        if age_years < 0.5:
            return "kitten"
        elif age_years >= 10:
            return "senior_cat"
        else:
            return "adult"
    else:  # dog
        if age_years < 0.5:
            return "puppy"
        elif age_years >= 9:
            return "senior_dog"
        else:
            return "adult"


def apply_age_modifiers(
    detected_symptoms: List[str],
    current_escalation: str,
    age_years: Optional[float] = None,
    species: str = "dog"
) -> Tuple[str, Optional[str]]:
    """
    Применяет возрастные модификаторы к escalation.
    Эскалация никогда не понижается.

    Аргументы:
        detected_symptoms: список нормализованных ключей симптомов
        current_escalation: текущий уровень
        age_years: возраст в годах (из профиля питомца)
        species: "dog" или "cat"

    Возвращает: (новый_уровень, причина) или (текущий_уровень, None)
    """
    result = current_escalation
    reason = None

    age_category = compute_age_category(age_years, species)

    # Выбираем нужную таблицу модификаторов
    if age_category == "senior_cat":
        table = SENIOR_CAT_ESCALATIONS
        reason_prefix = "Пожилая кошка (>10 лет)"
    elif age_category == "senior_dog":
        table = SENIOR_DOG_ESCALATIONS
        reason_prefix = "Пожилая собака (>9 лет)"
    elif age_category in ("puppy", "kitten"):
        table = PUPPY_KITTEN_ESCALATIONS
        label = "Котёнок" if age_category == "kitten" else "Щенок"
        reason_prefix = f"{label} (<6 мес)"
    else:
        # adult — возраст не влияет
        return result, None

    # Применяем модификаторы для каждого симптома
    for symptom in detected_symptoms:
        if symptom in table:
            new_level = table[symptom]
            if ESCALATION_ORDER.index(new_level) > ESCALATION_ORDER.index(result):
                result = new_level
                reason = f"{reason_prefix} — {symptom} требует повышенного внимания"

    return result, reason
