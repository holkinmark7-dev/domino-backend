"""
Onboarding v4 — Chat-native flow (Gemini-powered)
Replaces onboarding.py + onboarding_router.py
"""

# ── Константы полей (перенесены из старого onboarding.py) ──────────────────
REQUIRED_FIELDS = ["owner_name", "species", "name", "gender", "neutered", "age"]
OPTIONAL_FIELDS = ["breed", "color", "features", "chip_id", "stamp_id"]

# ── Контракт с chat.py ─────────────────────────────────────────────────────
# handle_onboarding() обязана вернуть dict со следующими ключами:
# {
#   "message_mode":             str,   # "ONBOARDING" | "ONBOARDING_COMPLETE" etc.
#   "next_question":            str | None,
#   "owner_name":               str | None,
#   "onboarding_phase":         str,   # "required" | "optional" | "complete"
#   "onboarding_step":          str | None,
#   "auto_follow":              bool,
#   "quick_replies":            list,
#   "input_type":               str,   # "text" | "photo" | "select"
#   "is_off_topic":             bool,
#   "onboarding_deterministic": bool,
#   "ai_response_override":     str | None,
#   "chat_history":             list,
#   "pet_profile_updated":      bool,
#   "pet_profile":              dict | None,
# }

def handle_onboarding(
    message_text: str,
    user_id: str,
    pet_id: str,
    pet_profile: dict,
    structured_data: dict,
    message_mode: str,
    supabase_client,
) -> dict:
    """
    Точка входа онбординга. Вызывается из chat.py строка 322.
    TODO: реализовать Gemini-powered chat onboarding flow.
    """
    # Временная заглушка — возвращает complete чтобы не блокировать систему
    return {
        "message_mode": message_mode,
        "next_question": None,
        "owner_name": None,
        "onboarding_phase": "complete",
        "onboarding_step": None,
        "auto_follow": False,
        "quick_replies": [],
        "input_type": "text",
        "is_off_topic": False,
        "onboarding_deterministic": False,
        "ai_response_override": None,
        "chat_history": [],
        "pet_profile_updated": False,
        "pet_profile": pet_profile,
    }


def is_off_topic(step: str, user_message: str) -> bool:
    """
    Определяет отвлечение от онбординга.
    TODO: реализовать через Gemini.
    """
    return False
