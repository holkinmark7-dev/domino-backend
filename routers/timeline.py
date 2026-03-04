from fastapi import APIRouter, Depends, Query, HTTPException, Request
from dependencies.auth import get_current_user, verify_pet_owner
from dependencies.limiter import limiter
from pydantic import BaseModel
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import date, datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta
from collections import Counter
import calendar
import re

from routers.services.heatmap import heatmap_score

router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

ESCALATION_ORDER = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


def _validate_date_str(date_str: str) -> str:
    """Validate YYYY-MM-DD format to prevent injection into DB queries."""
    if not date_str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise HTTPException(status_code=422, detail="date_str must be in YYYY-MM-DD format")
    try:
        date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=422, detail="date_str is not a valid date")
    return date_str


@router.get("/timeline/{pet_id}")
@limiter.limit("30/minute")
def get_timeline_month(pet_id: str, year: int = None, month: int = None, filter: str = "all", request: Request = None, current_user: dict = Depends(get_current_user)):
    verify_pet_owner(pet_id, current_user, supabase)
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

    # Build calendar_index from all rows (not filtered)
    calendar_index = {}
    for d in rows.data:
        d_date = d.get("date")
        if not d_date:
            continue
        max_esc = d.get("max_escalation", "LOW")
        calendar_index[d_date] = {
            "has_events": True,
            "max_escalation": max_esc,
            "heatmap_score": heatmap_score(max_esc),
            "event_count": d.get("event_count", 0),
            "has_critical": max_esc == "CRITICAL",
        }

    return {
        "year": _year,
        "month": _month,
        "days": filtered_days,
        "active_episodes": active_episodes.data,
        "has_events": len(rows.data) > 0,
        "recurring_patterns": recurring_patterns,
        "calendar_index": calendar_index,
    }


@router.get("/timeline/{pet_id}/day")
@limiter.limit("30/minute")
def get_timeline_day(pet_id: str, date_str: str, request: Request = None, current_user: dict = Depends(get_current_user)):
    verify_pet_owner(pet_id, current_user, supabase)
    date_str = _validate_date_str(date_str)
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
    if date_str:
        _validate_date_str(date_str)
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

    _event_count = len(events.data)
    _has_critical = max_esc == "CRITICAL"
    _heatmap = heatmap_score(max_esc)

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
        "event_count": _event_count,
        "has_critical": _has_critical,
        "heatmap_score": _heatmap,
        "updated_at": "now()",
    }

    supabase.table("timeline_days").upsert(
        row, on_conflict="pet_id,date"
    ).execute()

    return {"status": "recalculated", "date": _date, "max_escalation": max_esc}


@router.post("/timeline/{pet_id}/recalculate")
@limiter.limit("30/minute")
def recalculate_day_endpoint(pet_id: str, date_str: str = None, request: Request = None, current_user: dict = Depends(get_current_user)):
    verify_pet_owner(pet_id, current_user, supabase)
    return recalculate_day(pet_id=pet_id, date_str=date_str)


@router.get("/timeline/{pet_id}/filter")
@limiter.limit("30/minute")
def get_timeline_filtered(pet_id: str, event_type: str = "all", year: int = None, month: int = None, request: Request = None, current_user: dict = Depends(get_current_user)):
    verify_pet_owner(pet_id, current_user, supabase)
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
@limiter.limit("30/minute")
def close_episode(pet_id: str, episode_id: str, request: Request = None, current_user: dict = Depends(get_current_user)):
    verify_pet_owner(pet_id, current_user, supabase)
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
@limiter.limit("30/minute")
def add_clinical_action(pet_id: str, payload: ClinicalActionPayload, request: Request = None, current_user: dict = Depends(get_current_user)):
    verify_pet_owner(pet_id, current_user, supabase)
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


# ── Calendar heatmap endpoint ─────────────────────────────────────────────────
@router.get("/calendar/{pet_id}")
@limiter.limit("30/minute")
def get_calendar_heatmap(pet_id: str, months: int = Query(default=1, ge=1, le=6), request: Request = None, current_user: dict = Depends(get_current_user)):
    verify_pet_owner(pet_id, current_user, supabase)
    today = date.today()
    start_date = today - relativedelta(months=months)

    rows = (
        supabase.table("timeline_days")
        .select("date, max_escalation, event_count")
        .eq("pet_id", pet_id)
        .gte("date", str(start_date))
        .lte("date", str(today))
        .order("date", desc=False)
        .execute()
    )

    days = {}
    total_events = 0
    max_heatmap = 0
    critical_days = 0

    for d in rows.data:
        d_date = d.get("date")
        if not d_date:
            continue

        max_esc = d.get("max_escalation", "LOW")
        _count = d.get("event_count", 0) or 0
        _hs = heatmap_score(max_esc)
        _is_critical = max_esc == "CRITICAL"

        days[d_date] = {
            "heatmap_score": _hs,
            "event_count": _count,
            "has_critical": _is_critical,
        }

        total_events += _count
        if _hs > max_heatmap:
            max_heatmap = _hs
        if _is_critical:
            critical_days += 1

    return {
        "pet_id": pet_id,
        "period": {
            "from": str(start_date),
            "to": str(today),
        },
        "days": days,
        "summary": {
            "total_events": total_events,
            "days_with_events": len(days),
            "max_heatmap_score": max_heatmap,
            "critical_days": critical_days,
        },
    }
