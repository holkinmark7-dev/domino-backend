from datetime import datetime, timezone
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── SQL migration — run once in Supabase SQL editor ───────────────────────────
#
# Initial schema (create if not exists):
# DROP TABLE IF EXISTS episodes;
# CREATE TABLE episodes (
#     id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
#     pet_id            UUID        NOT NULL,
#     episode_type      TEXT        NOT NULL,   -- 'symptom' | 'medication'
#     normalized_key    TEXT        NOT NULL,
#     status            TEXT        NOT NULL DEFAULT 'active',  -- 'active' | 'resolved'
#     started_at        TIMESTAMPTZ DEFAULT NOW(),
#     last_event_at     TIMESTAMPTZ DEFAULT NOW(),
#     resolved_at       TIMESTAMPTZ,
#     last_event_id     UUID,
#     escalation_level  TEXT        NOT NULL DEFAULT 'LOW',
#     phase             TEXT        NOT NULL DEFAULT 'initial',
#     symptom_count     INT         NOT NULL DEFAULT 1,
#     recurrence_count  INT         NOT NULL DEFAULT 0,
#     created_at        TIMESTAMPTZ DEFAULT NOW(),
#     updated_at        TIMESTAMPTZ DEFAULT NOW()
# );
#
# Uniqueness constraint (one active episode per pet + type + key):
# CREATE UNIQUE INDEX IF NOT EXISTS episodes_active_unique
#     ON episodes (pet_id, episode_type, normalized_key)
#     WHERE status = 'active';
#
# If upgrading from pre-v4.4 schema (add missing columns):
# ALTER TABLE episodes ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMPTZ;
# ALTER TABLE episodes ADD COLUMN IF NOT EXISTS escalation_level TEXT DEFAULT 'LOW';
# ALTER TABLE episodes ADD COLUMN IF NOT EXISTS phase TEXT DEFAULT 'initial';
# ALTER TABLE episodes ADD COLUMN IF NOT EXISTS symptom_count INT DEFAULT 1;
# ALTER TABLE episodes ADD COLUMN IF NOT EXISTS recurrence_count INT DEFAULT 0;
# UPDATE episodes SET last_event_at = updated_at WHERE last_event_at IS NULL;
# UPDATE episodes SET escalation_level = 'LOW' WHERE escalation_level IS NULL;
#
# If upgrading from escalation → escalation_level rename:
# ALTER TABLE episodes RENAME COLUMN escalation TO escalation_level;
# ─────────────────────────────────────────────────────────────────────────────

_ESC_ORDER = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


def _compute_phase(symptom_count: int) -> str:
    """Compute episode phase based on symptom count."""
    if symptom_count <= 1:
        return "initial"
    if symptom_count <= 4:
        return "stable"
    return "escalating"


def _max_escalation(a: str, b: str) -> str:
    """Return the higher of two escalation levels. Never lowers."""
    if _ESC_ORDER.get(b, 0) > _ESC_ORDER.get(a, 0):
        return b
    return a


RESOLUTION_PHRASES = [
    "перестало",
    "больше не",
    "всё прошло",
    "все прошло",
    "уже нормально",
    "уже норм",
    "прекратилось",
    "прекратилась",
    "курс закончили",
    "закончили курс",
    "закончили приём",
    "перестал давать",
]


def _is_resolution(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in RESOLUTION_PHRASES)


def _normalize_medication(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized else None


def _get_active_episode(pet_id: str, episode_type: str, normalized_key: str) -> dict | None:
    result = (
        supabase.table("episodes")
        .select("*")
        .eq("pet_id", pet_id)
        .eq("episode_type", episode_type)
        .eq("normalized_key", normalized_key)
        .eq("status", "active")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _create_episode(
    pet_id: str,
    episode_type: str,
    normalized_key: str,
    event_id: str | None,
    escalation_level: str = "LOW",
) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "pet_id": pet_id,
        "episode_type": episode_type,
        "normalized_key": normalized_key,
        "status": "active",
        "started_at": now,
        "last_event_at": now,
        "escalation_level": escalation_level,
        "phase": "initial",
        "symptom_count": 1,
        "recurrence_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    if event_id:
        payload["last_event_id"] = event_id
    try:
        result = supabase.table("episodes").insert(payload).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"[episode_manager] create failed: {e}")
        return None


def _update_episode(
    episode_id: str,
    event_id: str | None,
    escalation_level: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "updated_at": now,
        "last_event_at": now,
    }
    if event_id:
        payload["last_event_id"] = event_id
    if escalation_level:
        payload["escalation_level"] = escalation_level

    # Increment symptom_count and recompute phase
    try:
        row = (
            supabase.table("episodes")
            .select("symptom_count")
            .eq("id", episode_id)
            .single()
            .execute()
        )
        if row.data:
            current_count = row.data.get("symptom_count") or 0
            new_count = current_count + 1
            payload["symptom_count"] = new_count
            payload["phase"] = _compute_phase(new_count)
    except Exception:
        pass  # Non-critical — continue without count/phase update

    supabase.table("episodes").update(payload).eq("id", episode_id).execute()


def _resolve_episode(episode_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    supabase.table("episodes").update({
        "status": "resolved",
        "resolved_at": now,
        "updated_at": now,
    }).eq("id", episode_id).execute()


def _handle_key(
    pet_id: str,
    episode_type: str,
    normalized_key: str,
    is_resolution: bool,
    event_id: str | None,
    escalation_level: str | None = None,
) -> dict:
    # ── Resolution path ───────────────────────────────────────────────────────
    if is_resolution:
        active = _get_active_episode(pet_id, episode_type, normalized_key)
        if active:
            _resolve_episode(active["id"])
            return {"episode_id": active["id"], "action": "resolved"}
        return {"episode_id": None, "action": "standalone"}

    # ── Continuation path ─────────────────────────────────────────────────────
    active = _get_active_episode(pet_id, episode_type, normalized_key)
    if active:
        # Escalation invariant: episode escalation never decreases
        current_esc = active.get("escalation_level") or "LOW"
        new_esc = _max_escalation(current_esc, escalation_level or "LOW")
        _update_episode(active["id"], event_id, new_esc)
        return {"episode_id": active["id"], "action": "continued"}

    # ── Create new episode ────────────────────────────────────────────────────
    ep = _create_episode(pet_id, episode_type, normalized_key, event_id, escalation_level or "LOW")
    if ep:
        return {"episode_id": ep["id"], "action": "created"}

    # ── Race-condition fallback ───────────────────────────────────────────────
    # _create_episode returned None — DB unique constraint likely rejected the
    # insert because a concurrent request already created the episode.
    # Retry: fetch the newly-created active episode and treat as continuation.
    active = _get_active_episode(pet_id, episode_type, normalized_key)
    if active:
        current_esc = active.get("escalation_level") or "LOW"
        new_esc = _max_escalation(current_esc, escalation_level or "LOW")
        _update_episode(active["id"], event_id, new_esc)
        return {"episode_id": active["id"], "action": "continued"}

    return {"episode_id": None, "action": "standalone"}


def update_episode_escalation(episode_id: str, escalation_level: str) -> None:
    """
    Persist the final triage escalation to the episode row.
    Enforces monotonic invariant: episode escalation never decreases.
    Called from chat.py after all Medical Core layers have run.
    """
    try:
        row = (
            supabase.table("episodes")
            .select("escalation_level")
            .eq("id", episode_id)
            .single()
            .execute()
        )
        if row.data:
            current = row.data.get("escalation_level") or "LOW"
            new_esc = _max_escalation(current, escalation_level)
            if new_esc != current:
                supabase.table("episodes").update({
                    "escalation_level": new_esc,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", episode_id).execute()
    except Exception as e:
        print(f"[episode_manager] update_escalation failed: {e}")


def process_event(
    pet_id: str,
    symptom: str | None,
    medication: str | None,
    message_text: str,
    event_id: str | None = None,
    escalation_level: str | None = None,
) -> dict:
    """
    Main entry point for episode lifecycle management.

    Handles both symptom and medication episodes independently.
    Returns primary episode_id (symptom takes priority) and per-type results.

    escalation_level: caller's current escalation estimate (will be updated after
    Medical Core finishes via update_episode_escalation).
    """
    is_resolution = _is_resolution(message_text)
    result: dict = {}

    if symptom:
        result["symptom_episode"] = _handle_key(
            pet_id=pet_id,
            episode_type="symptom",
            normalized_key=symptom,
            is_resolution=is_resolution,
            event_id=event_id,
            escalation_level=escalation_level,
        )
    elif is_resolution:
        # Resolution without an extracted symptom — resolve most recent active symptom episode
        any_active = (
            supabase.table("episodes")
            .select("*")
            .eq("pet_id", pet_id)
            .eq("episode_type", "symptom")
            .eq("status", "active")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if any_active.data:
            ep = any_active.data[0]
            _resolve_episode(ep["id"])
            result["symptom_episode"] = {"episode_id": ep["id"], "action": "resolved"}
        else:
            result["symptom_episode"] = {"episode_id": None, "action": "standalone"}

    norm_med = _normalize_medication(medication)
    if norm_med:
        result["medication_episode"] = _handle_key(
            pet_id=pet_id,
            episode_type="medication",
            normalized_key=norm_med,
            is_resolution=is_resolution,
            event_id=event_id,
            escalation_level=None,  # medication episodes don't track clinical escalation
        )

    if not result:
        return {"episode_id": None, "action": "standalone"}

    primary = result.get("symptom_episode") or result.get("medication_episode") or {}
    return {
        "episode_id": primary.get("episode_id"),
        "action": primary.get("action", "standalone"),
        **result,
    }
