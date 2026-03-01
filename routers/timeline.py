from fastapi import APIRouter
from pydantic import BaseModel
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import date, datetime, timezone
from collections import Counter
import calendar

router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ESCALATION_ORDER = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


@router.get("/timeline/{pet_id}")
def get_timeline_month(pet_id: str, year: int = None, month: int = None, filter: str = "all"):
    today = date.today()
    _year = year or today.year
    _month = month or today.month

    first_day = date(_year, _month, 1)
    last_day = date(_year, _month, calendar.monthrange(_year, _month)[1])

    rows = (
        supabase.table("timeline_days")
        .select("*")
        .eq("pet_id", pet_id)
        .gte("date", str(first_day))
        .lte("date", str(last_day))
        .order("date", desc=False)
        .execute()
    )

    active_episodes = (
        supabase.table("episodes")
        .select("id, symptom_key, current_escalation, episode_phase, started_at, status")
        .eq("pet_id", pet_id)
        .eq("status", "active")
        .in_("current_escalation", ["MODERATE", "HIGH", "CRITICAL"])
        .order("started_at", desc=True)
        .limit(2)
        .execute()
    )

    # Recurring patterns: symptom_key appearing ≥3 times in the month
    month_episodes = (
        supabase.table("episodes")
        .select("symptom_key")
        .eq("pet_id", pet_id)
        .gte("started_at", str(first_day))
        .lte("started_at", f"{last_day}T23:59:59")
        .execute()
    )
    symptom_counts = Counter(
        ep.get("symptom_key") for ep in month_episodes.data if ep.get("symptom_key")
    )
    recurring_patterns = [
        {"symptom_key": k, "count": v} for k, v in symptom_counts.items() if v >= 3
    ]

    # Apply filter
    filtered_days = rows.data
    if filter == "episodes":
        filtered_days = [d for d in filtered_days if d.get("has_episode")]
    elif filter == "vet_visit":
        filtered_days = [d for d in filtered_days if d.get("vet_visit")]
    elif filter == "vaccination":
        filtered_days = [d for d in filtered_days if d.get("vaccination")]
    elif filter == "medication_started":
        filtered_days = [d for d in filtered_days if d.get("medication_started")]

    return {
        "year": _year,
        "month": _month,
        "days": filtered_days,
        "active_episodes": active_episodes.data,
        "has_events": len(rows.data) > 0,
        "recurring_patterns": recurring_patterns,
    }


@router.get("/timeline/{pet_id}/day")
def get_timeline_day(pet_id: str, date_str: str):
    day_row = (
        supabase.table("timeline_days")
        .select("*")
        .eq("pet_id", pet_id)
        .eq("date", date_str)
        .single()
        .execute()
    )

    events = (
        supabase.table("events")
        .select("*")
        .eq("pet_id", pet_id)
        .gte("created_at", f"{date_str}T00:00:00")
        .lte("created_at", f"{date_str}T23:59:59")
        .order("created_at", desc=False)
        .execute()
    )

    episodes = (
        supabase.table("episodes")
        .select("*")
        .eq("pet_id", pet_id)
        .lte("started_at", f"{date_str}T23:59:59")
        .or_(f"closed_at.is.null,closed_at.gte.{date_str}T00:00:00")
        .execute()
    )

    return {
        "date": date_str,
        "summary": day_row.data if day_row.data else None,
        "events": events.data,
        "episodes": episodes.data,
    }


def recalculate_day(pet_id: str, date_str: str = None):
    _date = date_str or str(date.today())

    events = (
        supabase.table("events")
        .select("*")
        .eq("pet_id", pet_id)
        .gte("created_at", f"{_date}T00:00:00")
        .lte("created_at", f"{_date}T23:59:59")
        .execute()
    )

    medical_events = (
        supabase.table("events")
        .select("*")
        .eq("pet_id", pet_id)
        .eq("type", "medical_event")
        .gte("created_at", f"{_date}T00:00:00")
        .lte("created_at", f"{_date}T23:59:59")
        .execute()
    )

    max_esc = "LOW"
    has_episode = False
    episode_id = None
    episode_phase = None

    for e in medical_events.data:
        content = e.get("content") or {}
        if isinstance(content, dict):
            esc = content.get("escalation") or content.get("urgency_score")
            if isinstance(esc, int):
                esc = ["LOW", "LOW", "MODERATE", "CRITICAL"][min(esc, 3)]
            if esc and esc in ESCALATION_ORDER:
                if ESCALATION_ORDER[esc] > ESCALATION_ORDER[max_esc]:
                    max_esc = esc
            if content.get("episode_id"):
                has_episode = True
                episode_id = content.get("episode_id")
                episode_phase = content.get("episode_phase")

    all_types = [e.get("type") for e in events.data]

    documents_count = sum(1 for t in all_types if t == "document")

    # healthy_days: consecutive days with LOW before _date
    _prev_days = (
        supabase.table("timeline_days")
        .select("max_escalation")
        .eq("pet_id", pet_id)
        .lt("date", _date)
        .order("date", desc=True)
        .limit(30)
        .execute()
    )
    healthy_days = 0
    for d in _prev_days.data:
        if d.get("max_escalation", "LOW") == "LOW":
            healthy_days += 1
        else:
            break

    row = {
        "pet_id": pet_id,
        "date": _date,
        "max_escalation": max_esc,
        "has_episode": has_episode,
        "episode_id": episode_id,
        "episode_phase": episode_phase,
        "vet_visit": "vet_visit" in all_types,
        "medication_started": "medication_started" in all_types,
        "medication_stopped": "medication_stopped" in all_types,
        "vaccination": "vaccination" in all_types,
        "documents_count": documents_count,
        "healthy_days": healthy_days,
        "updated_at": "now()",
    }

    supabase.table("timeline_days").upsert(
        row, on_conflict="pet_id,date"
    ).execute()

    return {"status": "recalculated", "date": _date, "max_escalation": max_esc}


@router.post("/timeline/{pet_id}/recalculate")
def recalculate_day_endpoint(pet_id: str, date_str: str = None):
    return recalculate_day(pet_id=pet_id, date_str=date_str)


@router.get("/timeline/{pet_id}/filter")
def get_timeline_filtered(pet_id: str, event_type: str = "all", year: int = None, month: int = None):
    today = date.today()
    _year = year or today.year
    _month = month or today.month

    first_day = date(_year, _month, 1)
    last_day = date(_year, _month, calendar.monthrange(_year, _month)[1])

    query = (
        supabase.table("timeline_days")
        .select("*")
        .eq("pet_id", pet_id)
        .gte("date", str(first_day))
        .lte("date", str(last_day))
        .order("date", desc=False)
    )

    if event_type == "episodes":
        query = query.eq("has_episode", True)
    elif event_type == "vet_visit":
        query = query.eq("vet_visit", True)
    elif event_type == "vaccination":
        query = query.eq("vaccination", True)
    elif event_type == "medication":
        query = query.eq("medication_started", True)

    rows = query.execute()

    return {
        "year": _year,
        "month": _month,
        "filter": event_type,
        "days": rows.data,
        "has_events": len(rows.data) > 0,
    }


# ── Close episode ────────────────────────────────────────────────────────────
@router.post("/timeline/{pet_id}/episode/{episode_id}/close")
def close_episode(pet_id: str, episode_id: str):
    now_iso = datetime.now(timezone.utc).isoformat()

    supabase.table("episodes").update({
        "status": "closed",
        "closed_at": now_iso,
    }).eq("id", episode_id).eq("pet_id", pet_id).execute()

    recalculate_day(pet_id=pet_id)

    return {"status": "closed", "episode_id": episode_id, "closed_at": now_iso}


# ── Add clinical action ─────────────────────────────────────────────────────
class ClinicalActionPayload(BaseModel):
    type: str  # e.g. "vet_visit", "medication_started", "vaccination", "document"
    title: str = ""
    content: dict = {}
    episode_id: str = None


@router.post("/timeline/{pet_id}/action")
def add_clinical_action(pet_id: str, payload: ClinicalActionPayload):
    now_iso = datetime.now(timezone.utc).isoformat()

    event_row = {
        "pet_id": pet_id,
        "type": payload.type,
        "title": payload.title,
        "content": payload.content,
        "episode_id": payload.episode_id,
        "created_at": now_iso,
    }

    result = supabase.table("events").insert(event_row).execute()

    recalculate_day(pet_id=pet_id)

    return {
        "status": "created",
        "event": result.data[0] if result.data else event_row,
    }
