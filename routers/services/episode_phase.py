"""
Episode phase computation — display-only.

Derived from episode duration. Does NOT affect escalation, recurrence,
episode engine, or database state.

Thresholds:
    initial   → duration < 12h
    ongoing   → 12h ≤ duration < 48h
    prolonged → duration ≥ 48h
    None      → "initial" (safe default, treated as very early episode)
"""


def compute_episode_phase(duration_hours: float | None) -> str:
    """
    Return the display phase for an episode based on its duration.

    Args:
        duration_hours: Episode duration in hours, or None if not available.

    Returns:
        "initial"   — duration < 12h, or duration is None.
        "ongoing"   — 12h ≤ duration < 48h.
        "prolonged" — duration ≥ 48h.
    """
    if duration_hours is None:
        return "initial"
    if duration_hours < 12:
        return "initial"
    if duration_hours < 48:
        return "ongoing"
    return "prolonged"
