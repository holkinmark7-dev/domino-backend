"""
Chat History API

GET /chat/history/{pet_id}

Returns the chronological message list for a pet.
Each item carries role, content, and triage enrichment so the mobile client
can call setMessages(data) directly.

Data sources (both read-only):
  - chat     table → user messages (role: "user")
  - events   table → medical_event rows, linked via source_chat_id, carry
                     structured_data, urgency_score → risk_level,
                     followup_instructions

Returns chronological message list for a pet.
Both user and AI messages are included (role: "user" | "ai").
User messages are enriched with triage data from linked medical events.
"""
import json

from fastapi import APIRouter
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY

router = APIRouter()
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Mirrors risk_level_map in chat.py (line 1223)
_RISK_MAP = {0: "normal", 1: "low", 2: "moderate", 3: "high"}
_FOLLOWUP_MSG = (
    "Следите за дыханием, аппетитом и активностью в течение следующих 24 часов."
)


def _parse_medical_events(pet_id: str) -> dict:
    """
    Fetch all medical_event rows for a pet and return a dict keyed by
    source_chat_id → parsed content dict.

    Rows without a valid source_chat_id or parseable content are skipped.
    """
    result = (
        supabase.table("events")
        .select("content")
        .eq("pet_id", pet_id)
        .eq("type", "medical_event")
        .execute()
    )
    lookup: dict = {}
    for ev in (result.data or []):
        raw = ev.get("content")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
        if not isinstance(raw, dict):
            continue
        src_id = raw.get("source_chat_id")
        if src_id and src_id not in lookup:
            lookup[src_id] = raw
    return lookup


@router.get("/chat/history/{pet_id}")
def get_chat_history(pet_id: str):
    """
    Return chronological chat messages for the given pet.

    Each message object:
      id                   – chat record UUID
      role                 – "user" (AI persistence is not yet implemented)
      content              – original user text
      structured_data      – triage extraction from the message, or null
      risk_level           – "normal" | "low" | "moderate" | "high"
      followup_instructions – guidance string if risk ≥ moderate, else null
    """
    # ── 1. All messages (chronological, oldest first) ─────────────────────────
    chat_result = (
        supabase.table("chat")
        .select("id, role, message, created_at")
        .eq("pet_id", pet_id)
        .order("created_at", desc=False)
        .execute()
    )
    chat_rows = chat_result.data or []

    # ── 2. Triage enrichment: medical events keyed by source_chat_id ──────────
    med_lookup = _parse_medical_events(pet_id)

    # ── 3. Build response list ────────────────────────────────────────────────
    messages = []
    for row in chat_rows:
        chat_id = row.get("id")
        role = row.get("role") or "user"  # NULL legacy rows default to "user"

        if role == "ai":
            # AI messages carry no triage enrichment
            messages.append({
                "id": chat_id,
                "role": "ai",
                "content": row.get("message") or "",
                "structured_data": None,
                "risk_level": "normal",
                "followup_instructions": None,
            })
            continue

        # User message — enrich with triage data if a medical event was linked
        med = med_lookup.get(chat_id)

        if med:
            raw_u = med.get("urgency_score")
            urgency = raw_u if isinstance(raw_u, int) and 0 <= raw_u <= 3 else None
            risk_level = _RISK_MAP.get(urgency, "normal")
            followup = _FOLLOWUP_MSG if isinstance(urgency, int) and urgency >= 2 else None
            # Strip internal tracking key before exposing to client
            structured_data = {k: v for k, v in med.items() if k != "source_chat_id"}
        else:
            risk_level = "normal"
            followup = None
            structured_data = None

        messages.append({
            "id": chat_id,
            "role": "user",
            "content": row.get("message") or "",
            "structured_data": structured_data,
            "risk_level": risk_level,
            "followup_instructions": followup,
            "escalation": med.get("escalation") if med else None,
        })

    return messages
