from datetime import datetime, timedelta, timezone
from routers.services.memory import get_medical_events

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
