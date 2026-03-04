"""
chat_helpers.py — Pure helper functions extracted from routers/chat.py.
No IO, no Supabase, no OpenAI.
"""

import re
from datetime import date

from routers.services.risk_engine import ESCALATION_ORDER


def strip_markdown_json(raw: str) -> str:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def escalate_min(current: str, target: str) -> str:
    if ESCALATION_ORDER[current] < ESCALATION_ORDER[target]:
        return target
    return current


def compute_age_years(birth_date_str) -> float | None:
    if not birth_date_str:
        return None
    try:
        bd = date.fromisoformat(str(birth_date_str)[:10])
        return (date.today() - bd).days / 365.25
    except (ValueError, TypeError):
        return None


def count_questions(text: str) -> int:
    """
    Count logical questions, not raw '?' symbols.
    Rules:
    - Consecutive '?' count as ONE question.
    - Ignore '?' inside quotes.
    - Ignore markdown/code blocks.
    """
    if not isinstance(text, str):
        return 0

    # remove code blocks
    cleaned = re.sub(r"```[\s\S]*?```", "", text)

    # remove quoted text (supports multiple quote styles)
    quote_patterns = [
        r"\".*?\"",        # "..."
        r"\'.*?\'",        # '...'
        r"«.*?»",          # «...»
        r"\u201c.*?\u201d",  # \u201c...\u201d
        r"\u2018.*?\u2019",  # \u2018...\u2019
    ]
    for pattern in quote_patterns:
        cleaned = re.sub(pattern, "", cleaned)

    # collapse multiple ?
    cleaned = re.sub(r"\?+", "?", cleaned)

    return cleaned.count("?")


def build_missing_facts(structured_data: dict) -> list:
    missing = []

    if not isinstance(structured_data, dict):
        return missing

    symptom = structured_data.get("symptom")

    # blood unknown
    if "blood" not in structured_data:
        missing.append("blood")

    # drinking unknown
    if "refusing_water" not in structured_data:
        missing.append("drinking")

    # cross GI уточнения
    if symptom == "diarrhea":
        if structured_data.get("vomiting") is None:
            missing.append("vomiting")

    if symptom == "vomiting":
        if structured_data.get("diarrhea") is None:
            missing.append("diarrhea")

    return list(set(missing))


def apply_monotonic_lock(decision: dict, episode_id, previous_events: list) -> None:
    """
    Ensure escalation within an episode is monotonically non-decreasing.
    Mutates decision in place. Sets 'monotonic_corrected' debug flag.
    """
    previous_max = None
    for e in previous_events:
        content = e.get("content")
        if not isinstance(content, dict):
            continue
        if content.get("episode_id") == episode_id:
            prev_urgency = content.get("urgency_score")
            if isinstance(prev_urgency, int):
                if previous_max is None or prev_urgency > previous_max:
                    previous_max = prev_urgency

    if previous_max is not None:
        current_idx = ESCALATION_ORDER[decision["escalation"]]
        previous_idx = previous_max
        if current_idx < previous_idx:
            decision["escalation"] = list(ESCALATION_ORDER.keys())[previous_idx]
            decision["monotonic_corrected"] = True
        else:
            decision["monotonic_corrected"] = False
    else:
        decision["monotonic_corrected"] = False


def compute_episode_phase_v1(
    current_escalation: str,
    previous_max_urgency: int | None,
    monotonic_corrected: bool,
    systemic_adjusted: bool,
    cross_class_override: bool,
) -> str:
    """
    Classify the clinical trajectory of the current episode turn.

    Returns one of:
      "initial"    — no prior escalation data (first event in episode)
      "worsening"  — current escalation > previous
      "stable"     — current == previous, no new systemic / cross-class driver
      "progressing"— current == previous BUT driven by systemic_adjusted or cross_class
      "improving"  — monotonic lock held the level; raw would have been lower

    Never mutates inputs. Pure function.
    """
    if previous_max_urgency is None:
        return "initial"

    current_idx = ESCALATION_ORDER[current_escalation]

    # improving: lock corrected upward → the underlying trend is better
    if monotonic_corrected:
        return "improving"

    if current_idx > previous_max_urgency:
        return "worsening"

    if current_idx == previous_max_urgency:
        if systemic_adjusted or cross_class_override:
            return "progressing"
        return "stable"

    # current_idx < previous_max_urgency should be impossible post-lock
    return "stable"


def _classify_message_mode(structured_data: dict, message_text: str) -> str:
    """
    Classify the message into one of three routing modes:
      "CASUAL"   — no symptom, no lifestyle keyword (greeting, question about pet)
      "PROFILE"  — lifestyle / care / nutrition question
      "CLINICAL" — symptom detected
    """
    if not isinstance(structured_data, dict) or "error" in structured_data:
        return "CASUAL"

    # CLINICAL: symptom detected (highest priority)
    if structured_data.get("symptom"):
        return "CLINICAL"

    # PROFILE: lifestyle / care keywords
    _msg = message_text.lower()
    _profile_keywords = [
        "корм", "кормить", "питание", "еда", "вода", "поить",
        "прогулк", "гулять", "игр", "игруш",
        "уход", "мыть", "купать", "чесать", "стричь",
        "прививк", "вакцин", "паразит", "глист", "блох",
        "поведени", "характер", "порода", "возраст",
        "сколько", "как часто", "когда",
    ]
    if any(k in _msg for k in _profile_keywords):
        return "PROFILE"

    return "CASUAL"
