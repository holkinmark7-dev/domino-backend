from datetime import datetime, timedelta, timezone
from routers.services.memory import get_medical_events
from .clarification_engine import match_owner_phrase, needs_clarification
from .symptom_registry_v2 import SYMPTOM_REGISTRY

CLINICAL_ENGINE_VERSION = "v1.0.0-FROZEN"

CLINICAL_RULES = {
    "vomiting": {
        "critical_last_hour": 3,
        "high_last_day": 5,
        "moderate_last_day": 3,
    },
    "diarrhea": {
        "critical_last_hour": 3,
        "high_last_day": 5,
        "moderate_last_day": 3,
    },
}


def _parse_event_time(created_at: str | None):
    if not created_at:
        return None
    try:
        dt = datetime.fromisoformat(created_at)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def get_symptom_stats(pet_id: str, symptom_key: str) -> dict:
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)

    events = get_medical_events(pet_id=pet_id, limit=200)

    today = 0
    last_hour = 0
    last_24h = 0

    for e in events:
        content = e.get("content")
        if not isinstance(content, dict):
            continue

        if content.get("symptom") != symptom_key:
            continue

        event_time = _parse_event_time(e.get("created_at"))
        if not event_time:
            continue

        if event_time.date() == now.date():
            today += 1

        if event_time >= one_hour_ago:
            last_hour += 1

        if event_time >= day_ago:
            last_24h += 1

    return {
        "today": today,
        "last_hour": last_hour,
        "last_24h": last_24h,
    }


def get_vomiting_stats(pet_id: str) -> dict:
    return get_symptom_stats(pet_id, "vomiting")


def evaluate_clinical_escalation(symptom_key: str, stats: dict) -> str:
    rules = CLINICAL_RULES.get(symptom_key, {})
    last_hour = stats.get("last_hour", 0)
    today = stats.get("today", 0)

    if last_hour >= rules.get("critical_last_hour", float("inf")):
        return "CRITICAL"
    elif today >= rules.get("high_last_day", float("inf")):
        return "HIGH"
    elif today >= rules.get("moderate_last_day", float("inf")):
        return "MODERATE"
    else:
        return "LOW"


def evaluate_vomiting_escalation(stats: dict) -> str:
    return evaluate_clinical_escalation("vomiting", stats)


def build_clinical_decision(symptom_key: str, stats: dict) -> dict:
    escalation = evaluate_clinical_escalation(symptom_key, stats)
    return {
        "symptom": symptom_key,
        "stats": stats,
        "escalation": escalation,
        "stop_questioning": escalation in ["MODERATE", "HIGH", "CRITICAL"],
        "override_urgency": escalation in ["HIGH", "CRITICAL"],
    }


def build_vomiting_decision(stats: dict) -> dict:
    return build_clinical_decision("vomiting", stats)


def apply_cross_symptom_override(pet_id: str, symptom_key: str, decision: dict) -> dict:
    events = get_medical_events(pet_id=pet_id, limit=100)

    has_recent_vomiting = False
    has_recent_diarrhea = False
    has_blood = False

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    for e in events:
        content = e.get("content")
        if not isinstance(content, dict):
            continue

        event_time = _parse_event_time(e.get("created_at"))
        if not event_time or event_time < day_ago:
            continue

        if content.get("symptom") == "vomiting":
            has_recent_vomiting = True

        if content.get("symptom") == "diarrhea":
            has_recent_diarrhea = True

        if content.get("blood") is True:
            has_blood = True

    escalation = decision.get("escalation")

    # Rule 1 & 2: blood + vomiting or diarrhea → raise to HIGH if below
    if has_blood and symptom_key in ["vomiting", "diarrhea"]:
        if escalation in ["LOW", "MODERATE"]:
            decision["escalation"] = "HIGH"

    # Rule 3: vomiting + diarrhea combo within 24h → raise to HIGH if below
    if has_recent_vomiting and has_recent_diarrhea:
        if escalation in ["LOW", "MODERATE"]:
            decision["escalation"] = "HIGH"

    return decision


def check_clarification_needed(
    user_message: str,
    extracted_symptoms: list,
    species: str = "dog"
) -> dict:
    """
    Проверяет нужен ли уточняющий вопрос перед ответом.

    Возвращает:
    {
        "needed": True/False,
        "question": "текст вопроса" или None,
        "symptom_key": "ключ симптома" или None,
        "all_symptoms": [список всех симптомов включая из фраз]
    }

    Логика:
    1. Распознаём дополнительные симптомы из живой речи
    2. Объединяем с extraction симптомами
    3. Если есть хоть один auto_critical → clarification НЕ нужна
    4. Если симптом один и он требует уточнения → вернуть вопрос
    5. Если симптомов несколько → clarification НЕ нужна (и так достаточно данных)
    """
    # Шаг 1: распознаём фразы из живой речи
    phrase_symptoms = match_owner_phrase(user_message)

    # Шаг 2: объединяем все симптомы без дублей
    all_symptoms = list(set(extracted_symptoms + phrase_symptoms))

    # Шаг 3: проверяем есть ли auto_critical симптом
    for symptom_key in all_symptoms:
        symptom_data = SYMPTOM_REGISTRY.get(symptom_key, {})
        if symptom_data.get("auto_critical", False):
            return {
                "needed": False,
                "question": None,
                "symptom_key": None,
                "all_symptoms": all_symptoms
            }

    # Шаг 4: если симптом один — проверяем нужно ли уточнение
    if len(all_symptoms) == 1:
        question = needs_clarification(all_symptoms[0])
        if question:
            return {
                "needed": True,
                "question": question,
                "symptom_key": all_symptoms[0],
                "all_symptoms": all_symptoms
            }

    # Шаг 5: несколько симптомов или нет вопроса — уточнение не нужно
    return {
        "needed": False,
        "question": None,
        "symptom_key": None,
        "all_symptoms": all_symptoms
    }
