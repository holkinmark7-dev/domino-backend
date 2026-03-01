"""
Recurrence detection for the Episode Clinical Layer.

check_recurrence() returns True if a pet has ≥3 resolved symptom episodes
for the same normalized_key within the last 30 days.

Rules:
  - Only counts status='resolved' episodes (active episodes are excluded)
  - Only counts episodes with resolved_at within the 30-day window
    (rows with NULL resolved_at are excluded automatically by the GTE filter)
  - Filters by episode_type='symptom' (medication recurrence is irrelevant)
  - Does NOT count the current active episode
"""
from datetime import datetime, timedelta, timezone

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def check_recurrence(pet_id: str, normalized_key: str) -> bool:
    """
    Returns True if pet has ≥3 resolved symptom episodes for normalized_key
    within the last 30 days.

    Args:
        pet_id:         Pet UUID as string.
        normalized_key: Symptom key (e.g. 'vomiting').

    Returns:
        True  → recurrence confirmed (≥3 resolved in window).
        False → not enough history, or query failed.
    """
    window_start = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    try:
        result = (
            supabase.table("episodes")
            .select("id")
            .eq("pet_id", pet_id)
            .eq("episode_type", "symptom")
            .eq("normalized_key", normalized_key)
            .eq("status", "resolved")
            .gte("resolved_at", window_start)
            .execute()
        )
        count = len(result.data) if result.data else 0
        return count >= 3
    except Exception as e:
        print(f"[recurrence] check failed: {e}")
        return False
