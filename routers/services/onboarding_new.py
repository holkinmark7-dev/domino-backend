"""
Onboarding v5 — Chat-native FSM (15 states).
Replaces onboarding.py + onboarding_router.py.
"""

from enum import Enum

from routers.services.memory import get_user_flags, update_user_flags


# ── Validation messages (used in Этап 5) ─────────────────────────────────────

VALIDATION_MESSAGES = {
    "owner_name_invalid":  "Хм, это имя? Просто хочу знать как к вам обращаться 😊",
    "age_unrealistic":     "47 — это рекорд! 😄 Наверное имеешь в виду 4 или 7?",
    "age_future_date":     "Похоже дата в будущем — уточни?",
    "age_too_young":       "Совсем кроха! Сколько месяцев примерно?",
    "breed_not_found":     "Такую не нашёл — похоже на {suggestion}? Или запишу как есть",
    "breed_mixed":         "Дворняга — это почётно! 🐕 Запишу как беспородный (метис). Ок?",
    "breed_unknown":       "Хотите — сфотографируйте, я попробую определить",
    "passport_unreadable": "Хм, не разберу текст — попробуй при лучшем освещении?",
    "species_unsupported": "Пока работаем только с кошками и собаками — но скоро добавим остальных! 🐹",
    "pet_name_empty":      "А как зовут вашего питомца?",
}


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
    GENDER          = "GENDER"             # Шаг 8a — пол (только для собак)
    NEUTERED        = "NEUTERED"           # Шаг 8b — кастрация/стерилизация
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
    OnboardingState.AGE:             OnboardingState.GENDER,
    OnboardingState.GENDER:          OnboardingState.NEUTERED,
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_owner_name(raw: str) -> str:
    return raw.strip().split()[0] if raw.strip() else raw.strip()


# ── State handlers ───────────────────────────────────────────────────────────

def _handle_welcome(user_input, pet_profile, user_flags):
    message = (
        "🐾 Привет! Я Домино.\n"
        "Я буду рядом с вашим питомцем — помогу следить за здоровьем, "
        "напомню о прививках и буду всегда на связи если что-то пойдёт не так.\n\n"
        "Прежде чем мы начнём — как вас зовут? 😊"
    )
    return _make_response(message, OnboardingState.OWNER_NAME, user_flags, pet_profile)


def _handle_owner_name(user_input, pet_profile, user_flags):
    owner_name = _extract_owner_name(user_input)
    user_flags["owner_name"] = owner_name

    message = (
        f"Приятно познакомиться, {owner_name}! 👋\n\n"
        "Скажите — что для вас сейчас важнее всего?"
    )
    return _make_response(
        message, OnboardingState.GOAL, user_flags, pet_profile,
        quick_replies=[
            "🐣 У меня новый питомец — хочу делать всё правильно",
            "💊 Хочу следить за здоровьем и прививками",
            "🏥 Есть конкретный вопрос по здоровью питомца",
            "📋 Хочу вести полную медкарту",
        ],
        input_type="quick_reply",
    )


def _handle_goal(user_input, pet_profile, user_flags):
    user_flags["onboarding_goal"] = user_input

    message = (
        "Отлично — вы по адресу. Именно для этого я и существую, "
        "и делаю это без лишней суеты 🐾\n\n"
        "Давайте познакомимся с вашим питомцем! "
        "Расскажите о нём — кто он, сколько лет, как его зовут. "
        "Пишите как захотите — я разберусь."
    )
    return _make_response(message, OnboardingState.PET_INTRO, user_flags, pet_profile)


def _handle_pet_intro(user_input, pet_profile, user_flags):
    user_flags["pet_intro_raw"] = user_input

    message = "Записал, спасибо! Уточню пару деталей 😊"
    return _make_response(message, OnboardingState.SPECIES_CLARIFY, user_flags, pet_profile)


def _handle_species_clarify(user_input, pet_profile, user_flags):
    species_raw = user_input.strip().lower()
    for prefix in ["🐱 ", "🐈 ", "🐩 "]:
        species_raw = species_raw.replace(prefix, "")
    user_flags["species"] = species_raw

    pet_name = pet_profile.get("name", "ваш питомец")
    message = f"{pet_name} — это кот или кошка? Или собака?"
    return _make_response(
        message, OnboardingState.PASSPORT_OFFER, user_flags, pet_profile,
        quick_replies=["🐱 Кот", "🐈 Кошка", "🐩 Собака"],
        input_type="quick_reply",
    )


def _handle_passport_offer(user_input, pet_profile, user_flags):
    pet_name = pet_profile.get("name", "вашего питомца")
    message = (
        f"Кстати — у {pet_name} есть ветеринарный паспорт? "
        "Если да, я могу прочитать его фото и заполнить карточку автоматически 📄"
    )
    return _make_response(
        message, OnboardingState.BREED, user_flags, pet_profile,
        quick_replies=["📸 Да, сфотографирую", "✍️ Нет, расскажу сам", "❓ Не знаю где он"],
        input_type="quick_reply",
    )


def _handle_passport_ocr(user_input, pet_profile, user_flags):
    message = (
        "Отлично! Сфотографируй главную страницу паспорта — "
        "ту где основные данные питомца. "
        "Можно чуть под углом, главное чтобы текст был виден 📄"
    )
    return _make_response(
        message, OnboardingState.BREED, user_flags, pet_profile,
        input_type="image",
    )


def _handle_breed(user_input, pet_profile, user_flags):
    pet_name = pet_profile.get("name", "питомца")
    message = (
        f"Хотите — сфотографируйте {pet_name}, "
        "и я постараюсь определить породу и окрас по фото 🔍\n"
        "Или вы уже знаете породу?"
    )
    return _make_response(
        message, OnboardingState.BREED_INSIGHT, user_flags, pet_profile,
        quick_replies=["📸 Сделаю фото — определите", "✍️ Знаю, скажу сам", "🤷 Не знаю породу"],
        input_type="quick_reply",
    )


def _handle_breed_insight(user_input, pet_profile, user_flags):
    breed = pet_profile.get("breed", "")
    pet_name = pet_profile.get("name", "ваш питомец")

    if breed:
        insight = f"{breed} — замечательный выбор! 😊"
    else:
        insight = "Отличный питомец! 😊"

    age_question = (
        f"Сколько лет {pet_name}? Если знаете точную дату — напишите её, "
        "если нет — просто год или примерный возраст 📅"
    )

    message = f"{insight}\n\n{age_question}"
    return _make_response(
        message, OnboardingState.AGE, user_flags, pet_profile,
        quick_replies=["Введу дату", "Только год", "Примерно N лет", "Не знаю"],
    )


def _handle_age(user_input, pet_profile, user_flags):
    user_flags["age_raw"] = user_input

    species = user_flags.get("species", "")
    if species == "кот":
        user_flags["gender"] = "самец"
        next_state = OnboardingState.NEUTERED
    elif species == "кошка":
        user_flags["gender"] = "самка"
        next_state = OnboardingState.NEUTERED
    else:
        next_state = OnboardingState.GENDER

    message = "Записал! 👍"
    return _make_response(message, next_state, user_flags, pet_profile)


def _handle_gender(user_input, pet_profile, user_flags):
    raw = user_input.strip().lower()
    if "мальчик" in raw:
        user_flags["gender"] = "самец"
    elif "девочка" in raw:
        user_flags["gender"] = "самка"
    else:
        user_flags["gender"] = raw

    pet_name = pet_profile.get("name", "ваш питомец")
    message = f"{pet_name} — мальчик или девочка?"
    return _make_response(
        message, OnboardingState.NEUTERED, user_flags, pet_profile,
        quick_replies=["🐾 Мальчик", "🐾 Девочка"],
        input_type="quick_reply",
    )


def _handle_neutered(user_input, pet_profile, user_flags):
    pet_name = pet_profile.get("name", "ваш питомец")
    gender = user_flags.get("gender", "")

    if gender == "самец":
        message = f"{pet_name} кастрирован?"
    else:
        message = f"{pet_name} стерилизована?"

    return _make_response(
        message, OnboardingState.PHOTO_AVATAR, user_flags, pet_profile,
        quick_replies=["✅ Да", "❌ Нет", "❓ Не знаю"],
        input_type="quick_reply",
    )


def _handle_photo_avatar(user_input, pet_profile, user_flags):
    pet_name = pet_profile.get("name", "питомца")
    message = (
        f"Последнее — хотите добавить фото {pet_name} для карточки? "
        "Любое любимое 📸"
    )
    return _make_response(
        message, OnboardingState.CONFIRM_SUMMARY, user_flags, pet_profile,
        quick_replies=["📷 Загрузить", "Пропустить пока"],
        input_type="quick_reply",
    )


def _handle_confirm_summary(user_input, pet_profile, user_flags):
    owner_name = user_flags.get("owner_name", "")
    pet_name = pet_profile.get("name", "ваш питомец")
    greeting = f"{owner_name}, " if owner_name else ""

    message = (
        f"Готово! Знакомьтесь — карточка {pet_name} 🎉\n\n"
        f"{greeting}{pet_name} теперь под надёжной защитой Домино.\n\n"
        "Можете спрашивать меня всё что угодно — о здоровье, питании, "
        "прививках, или просто если что-то кажется странным в поведении."
    )
    return _make_response(
        message, OnboardingState.COMPLETE, user_flags, pet_profile,
        quick_replies=[
            "💉 Когда нужны прививки?",
            "🍽 Чем лучше кормить?",
            "📋 Что ещё добавить в карточку?",
            "🩺 Задать вопрос по здоровью",
        ],
        input_type="quick_reply",
    )


def _handle_complete(user_input, pet_profile, user_flags):
    return _make_response("", OnboardingState.COMPLETE, user_flags, pet_profile)


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
    OnboardingState.GENDER:          _handle_gender,
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

    # Mark onboarding complete in DB
    if next_state == OnboardingState.COMPLETE:
        supabase_client.table("users").update(
            {"is_onboarded": True}
        ).eq("id", user_id).execute()

    return result
