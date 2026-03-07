"""
Onboarding v4 — Chat-native FSM (15 states).
Replaces onboarding.py + onboarding_router.py.
"""

from enum import Enum

from routers.services.memory import get_user_flags, update_user_flags


# ── FSM States ────────────────────────────────────────────────────────────────

class OnboardingState(str, Enum):
    WELCOME         = "WELCOME"
    OWNER_NAME      = "OWNER_NAME"
    GOAL            = "GOAL"
    FREE_TEXT_INTRO = "FREE_TEXT_INTRO"
    PARSE_FREE_TEXT = "PARSE_FREE_TEXT"
    CLARIFY_MISSING = "CLARIFY_MISSING"
    PASSPORT_OFFER  = "PASSPORT_OFFER"
    PASSPORT_OCR    = "PASSPORT_OCR"
    VISION_BREED    = "VISION_BREED"
    CHAT_FLOW       = "CHAT_FLOW"
    BREED_INSIGHT   = "BREED_INSIGHT"
    NEUTERED        = "NEUTERED"
    PHOTO_AVATAR    = "PHOTO_AVATAR"
    CONFIRM_SUMMARY = "CONFIRM_SUMMARY"
    COMPLETE        = "COMPLETE"


# ── Transition table ──────────────────────────────────────────────────────────

TRANSITIONS = {
    OnboardingState.WELCOME:         OnboardingState.OWNER_NAME,
    OnboardingState.OWNER_NAME:      OnboardingState.GOAL,
    OnboardingState.GOAL:            OnboardingState.FREE_TEXT_INTRO,
    OnboardingState.FREE_TEXT_INTRO:  OnboardingState.PARSE_FREE_TEXT,
    OnboardingState.PARSE_FREE_TEXT:  OnboardingState.CLARIFY_MISSING,
    OnboardingState.CLARIFY_MISSING: OnboardingState.PASSPORT_OFFER,
    OnboardingState.PASSPORT_OFFER:  OnboardingState.CHAT_FLOW,
    OnboardingState.PASSPORT_OCR:    OnboardingState.CHAT_FLOW,
    OnboardingState.VISION_BREED:    OnboardingState.BREED_INSIGHT,
    OnboardingState.CHAT_FLOW:       OnboardingState.BREED_INSIGHT,
    OnboardingState.BREED_INSIGHT:   OnboardingState.NEUTERED,
    OnboardingState.NEUTERED:        OnboardingState.PHOTO_AVATAR,
    OnboardingState.PHOTO_AVATAR:    OnboardingState.CONFIRM_SUMMARY,
    OnboardingState.CONFIRM_SUMMARY: OnboardingState.COMPLETE,
}


# ── State helpers ─────────────────────────────────────────────────────────────

def get_current_state(user_flags: dict) -> OnboardingState:
    state_str = user_flags.get("onboarding_state", OnboardingState.WELCOME.value)
    try:
        return OnboardingState(state_str)
    except ValueError:
        return OnboardingState.WELCOME


def set_state(user_flags: dict, state: OnboardingState) -> dict:
    user_flags["onboarding_state"] = state.value
    return user_flags


# ── Response builder ──────────────────────────────────────────────────────────

def _make_response(
    message: str,
    next_state: OnboardingState,
    user_flags: dict,
    pet_profile: dict = None,
    quick_replies: list = None,
    input_type: str = "text",
) -> dict:
    return {
        "message_mode": "ONBOARDING" if next_state != OnboardingState.COMPLETE else "ONBOARDING_COMPLETE",
        "next_question": next_state.value,
        "owner_name": user_flags.get("owner_name"),
        "onboarding_phase": "complete" if next_state == OnboardingState.COMPLETE else "required",
        "onboarding_step": next_state.value,
        "auto_follow": None,
        "quick_replies": quick_replies or [],
        "input_type": input_type,
        "is_off_topic": False,
        "onboarding_deterministic": True,
        "ai_response_override": message,
        "chat_history": [],
        "pet_profile_updated": None,
        "pet_profile": pet_profile or {},
    }


# ── State handlers (placeholders) ────────────────────────────────────────────

def _handle_welcome(user_input, pet_profile, user_flags):
    return _make_response(
        "[WELCOME] Плейсхолдер",
        TRANSITIONS[OnboardingState.WELCOME],
        user_flags, pet_profile,
    )


def _handle_owner_name(user_input, pet_profile, user_flags):
    return _make_response(
        "[OWNER_NAME] Плейсхолдер",
        TRANSITIONS[OnboardingState.OWNER_NAME],
        user_flags, pet_profile,
    )


def _handle_goal(user_input, pet_profile, user_flags):
    return _make_response(
        "[GOAL] Плейсхолдер",
        TRANSITIONS[OnboardingState.GOAL],
        user_flags, pet_profile,
    )


def _handle_free_text_intro(user_input, pet_profile, user_flags):
    return _make_response(
        "[FREE_TEXT_INTRO] Плейсхолдер",
        TRANSITIONS[OnboardingState.FREE_TEXT_INTRO],
        user_flags, pet_profile,
    )


def _handle_parse_free_text(user_input, pet_profile, user_flags):
    return _make_response(
        "[PARSE_FREE_TEXT] Плейсхолдер",
        TRANSITIONS[OnboardingState.PARSE_FREE_TEXT],
        user_flags, pet_profile,
    )


def _handle_clarify_missing(user_input, pet_profile, user_flags):
    return _make_response(
        "[CLARIFY_MISSING] Плейсхолдер",
        TRANSITIONS[OnboardingState.CLARIFY_MISSING],
        user_flags, pet_profile,
    )


def _handle_passport_offer(user_input, pet_profile, user_flags):
    return _make_response(
        "[PASSPORT_OFFER] Плейсхолдер",
        TRANSITIONS[OnboardingState.PASSPORT_OFFER],
        user_flags, pet_profile,
        quick_replies=["Сфотографировать паспорт", "Пропустить"],
        input_type="buttons",
    )


def _handle_passport_ocr(user_input, pet_profile, user_flags):
    return _make_response(
        "[PASSPORT_OCR] Плейсхолдер",
        TRANSITIONS[OnboardingState.PASSPORT_OCR],
        user_flags, pet_profile,
        input_type="photo",
    )


def _handle_vision_breed(user_input, pet_profile, user_flags):
    return _make_response(
        "[VISION_BREED] Плейсхолдер",
        TRANSITIONS[OnboardingState.VISION_BREED],
        user_flags, pet_profile,
        input_type="photo",
    )


def _handle_chat_flow(user_input, pet_profile, user_flags):
    return _make_response(
        "[CHAT_FLOW] Плейсхолдер",
        TRANSITIONS[OnboardingState.CHAT_FLOW],
        user_flags, pet_profile,
    )


def _handle_breed_insight(user_input, pet_profile, user_flags):
    return _make_response(
        "[BREED_INSIGHT] Плейсхолдер",
        TRANSITIONS[OnboardingState.BREED_INSIGHT],
        user_flags, pet_profile,
    )


def _handle_neutered(user_input, pet_profile, user_flags):
    return _make_response(
        "[NEUTERED] Плейсхолдер",
        TRANSITIONS[OnboardingState.NEUTERED],
        user_flags, pet_profile,
        quick_replies=["Да", "Нет"],
        input_type="buttons",
    )


def _handle_photo_avatar(user_input, pet_profile, user_flags):
    return _make_response(
        "[PHOTO_AVATAR] Плейсхолдер",
        TRANSITIONS[OnboardingState.PHOTO_AVATAR],
        user_flags, pet_profile,
        quick_replies=["Загрузить фото", "Пропустить"],
        input_type="buttons",
    )


def _handle_confirm_summary(user_input, pet_profile, user_flags):
    return _make_response(
        "[CONFIRM_SUMMARY] Плейсхолдер",
        TRANSITIONS[OnboardingState.CONFIRM_SUMMARY],
        user_flags, pet_profile,
        quick_replies=["Всё верно", "Исправить"],
        input_type="buttons",
    )


def _handle_complete(user_input, pet_profile, user_flags):
    return _make_response(
        "[COMPLETE] Онбординг завершён",
        OnboardingState.COMPLETE,
        user_flags, pet_profile,
    )


# ── State router ──────────────────────────────────────────────────────────────

_HANDLERS = {
    OnboardingState.WELCOME:         _handle_welcome,
    OnboardingState.OWNER_NAME:      _handle_owner_name,
    OnboardingState.GOAL:            _handle_goal,
    OnboardingState.FREE_TEXT_INTRO:  _handle_free_text_intro,
    OnboardingState.PARSE_FREE_TEXT:  _handle_parse_free_text,
    OnboardingState.CLARIFY_MISSING: _handle_clarify_missing,
    OnboardingState.PASSPORT_OFFER:  _handle_passport_offer,
    OnboardingState.PASSPORT_OCR:    _handle_passport_ocr,
    OnboardingState.VISION_BREED:    _handle_vision_breed,
    OnboardingState.CHAT_FLOW:       _handle_chat_flow,
    OnboardingState.BREED_INSIGHT:   _handle_breed_insight,
    OnboardingState.NEUTERED:        _handle_neutered,
    OnboardingState.PHOTO_AVATAR:    _handle_photo_avatar,
    OnboardingState.CONFIRM_SUMMARY: _handle_confirm_summary,
    OnboardingState.COMPLETE:        _handle_complete,
}


def route_state(state: OnboardingState, user_input: str, pet_profile: dict, user_flags: dict) -> dict:
    handler = _HANDLERS.get(state, _handle_welcome)
    return handler(user_input, pet_profile, user_flags)


# ── Public API (called by chat.py) ───────────────────────────────────────────

def handle_onboarding(
    message_text: str,
    user_id: str,
    pet_id: str,
    pet_profile: dict,
    structured_data: dict,
    message_mode: str,
    supabase_client,
) -> dict:
    """Entry point called from chat.py:322."""
    user_flags = get_user_flags(user_id)
    state = get_current_state(user_flags)

    # Already complete — pass through, don't block the system
    if state == OnboardingState.COMPLETE:
        return {
            "message_mode": message_mode,
            "next_question": None,
            "owner_name": user_flags.get("owner_name"),
            "onboarding_phase": "complete",
            "onboarding_step": None,
            "auto_follow": None,
            "quick_replies": [],
            "input_type": "text",
            "is_off_topic": False,
            "onboarding_deterministic": False,
            "ai_response_override": None,
            "chat_history": [],
            "pet_profile_updated": None,
            "pet_profile": pet_profile,
        }

    result = route_state(state, message_text, pet_profile, user_flags)

    # Persist new state
    next_state = OnboardingState(result["onboarding_step"])
    set_state(user_flags, next_state)
    update_user_flags(user_id, user_flags)

    return result
