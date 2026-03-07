"""
Onboarding v4 — Chat-native FSM (14 states).
Replaces onboarding.py + onboarding_router.py.
"""

from enum import Enum

from routers.services.memory import get_user_flags, update_user_flags


# ── FSM States ────────────────────────────────────────────────────────────────

class OnboardingState(str, Enum):
    WELCOME         = "WELCOME"            # Шаг 1 — первое сообщение бота
    OWNER_NAME      = "OWNER_NAME"         # Шаг 1 — ждём имя владельца
    GOAL            = "GOAL"               # Шаг 2 — зачем скачал приложение
    PET_INTRO       = "PET_INTRO"          # Шаг 3 — свободный текст про питомца
    SPECIES_CLARIFY = "SPECIES_CLARIFY"    # Шаг 4 — кот или собака (если не ясно)
    PASSPORT_OFFER  = "PASSPORT_OFFER"     # Шаг 5 — предложение сфотографировать паспорт
    PASSPORT_OCR    = "PASSPORT_OCR"       # Шаг 5 — ветка: пользователь выбрал паспорт
    BREED           = "BREED"              # Шаг 6 — порода (фото или текст)
    BREED_INSIGHT   = "BREED_INSIGHT"      # Шаг 6 — инсайт после ввода породы
    AGE             = "AGE"                # Шаг 7 — возраст / дата рождения
    GENDER_NEUTERED = "GENDER_NEUTERED"    # Шаг 8 — пол + кастрация/стерилизация
    PHOTO_AVATAR    = "PHOTO_AVATAR"       # Шаг 9 — фото питомца для карточки
    CONFIRM_SUMMARY = "CONFIRM_SUMMARY"    # Шаг 10 — финальная карточка питомца
    COMPLETE        = "COMPLETE"           # Онбординг завершён


# ── Transition table ──────────────────────────────────────────────────────────

TRANSITIONS = {
    OnboardingState.WELCOME:         OnboardingState.OWNER_NAME,
    OnboardingState.OWNER_NAME:      OnboardingState.GOAL,
    OnboardingState.GOAL:            OnboardingState.PET_INTRO,
    OnboardingState.PET_INTRO:       OnboardingState.SPECIES_CLARIFY,
    OnboardingState.SPECIES_CLARIFY: OnboardingState.PASSPORT_OFFER,
    OnboardingState.PASSPORT_OFFER:  OnboardingState.BREED,
    OnboardingState.PASSPORT_OCR:    OnboardingState.BREED,
    OnboardingState.BREED:           OnboardingState.BREED_INSIGHT,
    OnboardingState.BREED_INSIGHT:   OnboardingState.AGE,
    OnboardingState.AGE:             OnboardingState.GENDER_NEUTERED,
    OnboardingState.GENDER_NEUTERED: OnboardingState.PHOTO_AVATAR,
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
    return _make_response("[WELCOME]", OnboardingState.OWNER_NAME, user_flags, pet_profile)


def _handle_owner_name(user_input, pet_profile, user_flags):
    return _make_response("[OWNER_NAME]", OnboardingState.GOAL, user_flags, pet_profile)


def _handle_goal(user_input, pet_profile, user_flags):
    return _make_response("[GOAL]", OnboardingState.PET_INTRO, user_flags, pet_profile)


def _handle_pet_intro(user_input, pet_profile, user_flags):
    return _make_response("[PET_INTRO]", OnboardingState.SPECIES_CLARIFY, user_flags, pet_profile)


def _handle_species_clarify(user_input, pet_profile, user_flags):
    return _make_response("[SPECIES_CLARIFY]", OnboardingState.PASSPORT_OFFER, user_flags, pet_profile)


def _handle_passport_offer(user_input, pet_profile, user_flags):
    return _make_response(
        "[PASSPORT_OFFER]", OnboardingState.BREED, user_flags, pet_profile,
        quick_replies=["Сфотографировать паспорт", "Пропустить"],
        input_type="buttons",
    )


def _handle_passport_ocr(user_input, pet_profile, user_flags):
    return _make_response(
        "[PASSPORT_OCR]", OnboardingState.BREED, user_flags, pet_profile,
        input_type="photo",
    )


def _handle_breed(user_input, pet_profile, user_flags):
    return _make_response("[BREED]", OnboardingState.BREED_INSIGHT, user_flags, pet_profile)


def _handle_breed_insight(user_input, pet_profile, user_flags):
    return _make_response("[BREED_INSIGHT]", OnboardingState.AGE, user_flags, pet_profile)


def _handle_age(user_input, pet_profile, user_flags):
    return _make_response("[AGE]", OnboardingState.GENDER_NEUTERED, user_flags, pet_profile)


def _handle_gender_neutered(user_input, pet_profile, user_flags):
    return _make_response("[GENDER_NEUTERED]", OnboardingState.PHOTO_AVATAR, user_flags, pet_profile)


def _handle_photo_avatar(user_input, pet_profile, user_flags):
    return _make_response(
        "[PHOTO_AVATAR]", OnboardingState.CONFIRM_SUMMARY, user_flags, pet_profile,
        quick_replies=["Загрузить фото", "Пропустить"],
        input_type="buttons",
    )


def _handle_confirm_summary(user_input, pet_profile, user_flags):
    return _make_response(
        "[CONFIRM_SUMMARY]", OnboardingState.COMPLETE, user_flags, pet_profile,
        quick_replies=["Всё верно", "Исправить"],
        input_type="buttons",
    )


def _handle_complete(user_input, pet_profile, user_flags):
    return _make_response("[COMPLETE]", OnboardingState.COMPLETE, user_flags, pet_profile)


# ── State router ──────────────────────────────────────────────────────────────

_HANDLERS = {
    OnboardingState.WELCOME:         _handle_welcome,
    OnboardingState.OWNER_NAME:      _handle_owner_name,
    OnboardingState.GOAL:            _handle_goal,
    OnboardingState.PET_INTRO:       _handle_pet_intro,
    OnboardingState.SPECIES_CLARIFY: _handle_species_clarify,
    OnboardingState.PASSPORT_OFFER:  _handle_passport_offer,
    OnboardingState.PASSPORT_OCR:    _handle_passport_ocr,
    OnboardingState.BREED:           _handle_breed,
    OnboardingState.BREED_INSIGHT:   _handle_breed_insight,
    OnboardingState.AGE:             _handle_age,
    OnboardingState.GENDER_NEUTERED: _handle_gender_neutered,
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
