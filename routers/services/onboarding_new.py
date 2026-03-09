"""
Onboarding v5 — Chat-native FSM (15 states).
Replaces onboarding.py + onboarding_router.py.
"""

import random
import re
from datetime import date
from enum import Enum

from rapidfuzz import fuzz, process

from routers.services.breeds import ALL_BREEDS, _ALL_BREEDS_LOWER
from routers.services.memory import get_user_flags, update_user_flags
from routers.services.onboarding_gemini import (
    parse_pet_info, apply_parsed_to_flags, get_states_to_skip,
    generate_breed_insight, classify_onboarding_message,
)


# ── Name declension ──────────────────────────────────────────────────────────

def _decline_name(name: str, case: str) -> str:
    """
    Простое склонение кличек питомцев.
    case: "gen" — родительный (у Бобика)
          "dat" — дательный (Бобику)
          "acc" — винительный (сфотографируйте Бобика)
    Правила только для самых частых окончаний.
    Если не знаем как склонять — возвращаем имя как есть.
    """
    if not name:
        return name

    n = name.strip()
    low = n.lower()

    # Окончание на -а/-я (Барсика, Мурка → Мурки)
    if low.endswith("а"):
        stem = n[:-1]
        if case == "gen":   return stem + "и"
        if case == "dat":   return stem + "е"
        if case == "acc":   return stem + "у"

    if low.endswith("я"):
        stem = n[:-1]
        if case == "gen":   return stem + "и"
        if case == "dat":   return stem + "е"
        if case == "acc":   return stem + "ю"

    # Окончание на согласную (Бобик, Марс, Лорд)
    consonants = "бвгджзйклмнпрстфхцчшщ"
    if low[-1] in consonants:
        if case == "gen":   return n + "а"
        if case == "dat":   return n + "у"
        if case == "acc":   return n + "а"

    # Окончание на -ь (Огонь, Тень)
    if low.endswith("ь"):
        stem = n[:-1]
        if case == "gen":   return stem + "я"
        if case == "dat":   return stem + "ю"
        if case == "acc":   return stem + "я"

    # Всё остальное — не склоняем
    return n


# ── Pet name stop-words ───────────────────────────────────────────────────────

_PET_NAME_STOP_WORDS = {
    "мой", "моя", "наш", "наша", "питомец", "питомица", "животное",
    "кот", "кошка", "собака", "пёс", "пес", "котик", "собачка",
}

_MIXED_BREED_KEYWORDS = {
    "дворняга", "дворняжка", "метис", "метиска", "беспородный", "беспородная",
    "дворовый", "дворовая", "мешанка", "помесь", "полукровка",
    "нет породы", "без породы",
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


def _handle_off_topic(msg_type, user_input, current_state, user_flags, pet_profile):
    """
    Handle off-topic message during onboarding.
    Returns _make_response or None if msg_type == "answer".
    """
    if msg_type == "answer":
        return None

    pet_name = user_flags.get("pet_name", "питомца")
    user_flags["pending_question"] = user_input

    if msg_type == "question":
        response = random.choice([
            f"Отвечу обязательно — но сначала давайте закончим знакомство, чтобы я мог дать точный ответ именно для {pet_name}.",
            "Хороший вопрос. Закончим знакомство — и сразу разберёмся.",
            f"Запомнил вопрос. Ещё пара минут — и отвечу с учётом всего что знаю о {pet_name}.",
        ])
        return _make_response(response, current_state, user_flags, pet_profile,
                              quick_replies=["Хорошо, продолжим"])
    else:  # urgent
        response = random.choice([
            f"Это важно — разберёмся. Но сначала мне нужно знать кто {pet_name}, чтобы дать правильный совет. Буквально пара вопросов.",
            "Слышу вас. Давайте быстро закончим знакомство — без этого я не смогу дать точный совет.",
            "Понял, это срочно. Ещё минута — закончим знакомство, и сразу перейдём к этому.",
        ])
        return _make_response(response, current_state, user_flags, pet_profile,
                              quick_replies=["Хорошо, быстро заканчиваем"])


# ── Response builder ──────────────────────────────────────────────────────────

def _make_response(
    message: str,
    next_state: OnboardingState,
    user_flags: dict,
    pet_profile: dict = None,
    quick_replies: list = None,
    input_type: str = "text",
    auto_follow: bool = None,
    pet_card: dict = None,
) -> dict:
    return {
        "message_mode": "ONBOARDING" if next_state != OnboardingState.COMPLETE else "ONBOARDING_COMPLETE",
        "next_question": next_state.value,
        "owner_name": user_flags.get("owner_name"),
        "onboarding_phase": "complete" if next_state == OnboardingState.COMPLETE else "required",
        "onboarding_step": next_state.value,
        "auto_follow": auto_follow,
        "quick_replies": quick_replies or [],
        "input_type": input_type,
        "is_off_topic": False,
        "onboarding_deterministic": True,
        "ai_response_override": message,
        "chat_history": [],
        "pet_profile_updated": None,
        "pet_profile": pet_profile or {},
        "pet_id": None,
        "pet_name": user_flags.get("pet_name"),
        "pet_card": pet_card,
        "user_flags": {
            k: user_flags.get(k)
            for k in ("species", "pet_name", "breed", "birth_date",
                       "age_years", "gender", "neutered", "color")
        },
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_pet_from_flags(user_id: str, user_flags: dict, supabase_client) -> str | None:
    """
    Создаёт запись в таблице pets из user_flags.
    Возвращает pet_id или None при ошибке.
    """
    _species_map = {"кот": "cat", "кошка": "cat", "собака": "dog"}
    _gender_map = {"самец": "male", "самка": "female"}

    try:
        pet_data = {
            "user_id": user_id,
            "name":       user_flags.get("pet_name"),
            "species":    _species_map.get(user_flags.get("species", ""), user_flags.get("species")),
            "gender":     _gender_map.get(user_flags.get("gender", ""), user_flags.get("gender")),
            "neutered":   user_flags.get("neutered"),
            "birth_date": user_flags.get("birth_date"),
            "age_years":  user_flags.get("age_years"),
            "breed":      user_flags.get("breed"),
            "color":      user_flags.get("color"),
        }
        pet_data = {k: v for k, v in pet_data.items() if v is not None}

        result = supabase_client.table("pets").insert(pet_data).execute()
        if result.data:
            return result.data[0]["id"]
        return None
    except Exception:
        return None


def _extract_owner_name(raw: str) -> str:
    return raw.strip().split()[0] if raw.strip() else raw.strip()


# ── State handlers ───────────────────────────────────────────────────────────

def _handle_welcome(user_input, pet_profile, user_flags):
    greeting = user_flags.pop("_greeting_prefix", None)
    if greeting:
        opening = f"{greeting}! Я Dominik."
    else:
        opening = "Привет! Я Dominik."
    message = (
        f"{opening}\n"
        "Помогу следить за здоровьем вашего питомца — прививки, визиты к врачу, "
        "симптомы. Всё в одном месте, всегда под рукой.\n"
        "Как вас зовут?"
    )
    return _make_response(message, OnboardingState.OWNER_NAME, user_flags, pet_profile)


def _handle_owner_name(user_input, pet_profile, user_flags):
    owner_name = _extract_owner_name(user_input)

    # Validation: empty / too short / digits / special chars only
    if (
        len(owner_name) < 2
        or any(c.isdigit() for c in owner_name)
        or not re.search(r'[a-zA-Zа-яА-ЯёЁ]', owner_name)
    ):
        msg = random.choice([
            "Хм, это имя? Просто хочу знать как к вам обращаться.",
            "Не совсем понял — как вас зовут?",
        ])
        return _make_response(msg, OnboardingState.OWNER_NAME, user_flags, pet_profile)

    # Validation: too long
    if len(owner_name) > 30:
        msg = random.choice([
            "Длинновато — можно просто имя?",
            "Давайте просто имя, без фамилии.",
        ])
        return _make_response(msg, OnboardingState.OWNER_NAME, user_flags, pet_profile)

    user_flags["owner_name"] = owner_name

    message = (
        f"Приятно познакомиться, {owner_name}.\n"
        "С чего начнём?"
    )
    return _make_response(
        message, OnboardingState.GOAL, user_flags, pet_profile,
        quick_replies=[
            "У меня новый питомец",
            "Хочу следить за прививками",
            "Есть вопрос по здоровью",
            "Хочу вести медкарту",
        ],
        input_type="quick_reply",
    )


def _handle_goal(user_input, pet_profile, user_flags):
    user_flags["onboarding_goal"] = user_input

    _goal_reactions = {
        "У меня новый питомец": "Хороший момент чтобы начать всё правильно с самого начала.",
        "Хочу следить за прививками": "Буду напоминать сам — ничего не пропустите.",
        "Есть вопрос по здоровью": "Слушаю. Сначала познакомимся с питомцем, потом разберёмся.",
        "Хочу вести медкарту": "Хорошая привычка — всё в одном месте всегда под рукой.",
    }
    reaction = _goal_reactions.get(user_input, "Отлично.")

    pet_intro_text = (
        "Давайте познакомлюсь с вашим питомцем.\n"
        "Расскажите о нём — как его зовут, кто он, сколько лет?"
    )

    message = f"{reaction}\n\n{pet_intro_text}"
    return _make_response(
        message, OnboardingState.PET_INTRO, user_flags, pet_profile,
    )


def _handle_pet_intro(user_input, pet_profile, user_flags):
    # ── Confirmation flow: user confirming a suspicious pet name ──
    if user_flags.get("_pet_name_pending"):
        pending = user_flags.pop("_pet_name_pending")
        confirm = user_input.strip().lower()
        if confirm in ("да", "ок", "верно", "правильно", "угу", "ага"):
            user_flags["pet_name"] = pending
            message = f"{pending} — запомнил."
            return _make_response(
                message, OnboardingState.SPECIES_CLARIFY, user_flags, pet_profile,
                auto_follow=True,
            )
        else:
            # User said no — ask again
            return _make_response(
                "Тогда как зовут вашего питомца?",
                OnboardingState.PET_INTRO, user_flags, pet_profile,
            )

    # ── Off-topic detection ──
    msg_type = classify_onboarding_message(user_input, OnboardingState.PET_INTRO.value)
    off_topic = _handle_off_topic(msg_type, user_input, OnboardingState.PET_INTRO, user_flags, pet_profile)
    if off_topic:
        return off_topic

    user_flags["pet_intro_raw"] = user_input

    # Парсинг через Gemini
    parsed = parse_pet_info(user_input)
    user_flags = apply_parsed_to_flags(parsed, user_flags)

    # Сохранить какие шаги пропускаем
    skip = get_states_to_skip(parsed, user_flags)
    user_flags["onboarding_skip"] = [s.value for s in skip]

    # ── Pet name validation ──
    pet_name = parsed.get("pet_name") or user_flags.get("pet_name", "")

    if pet_name:
        name_lower = pet_name.strip().lower()

        # Too short (1 char)
        if len(pet_name.strip()) < 2:
            msg = random.choice([
                "Одна буква? Может, полное имя?",
                "Коротковато — как полностью зовут питомца?",
            ])
            return _make_response(msg, OnboardingState.PET_INTRO, user_flags, pet_profile)

        # Too long
        if len(pet_name.strip()) > 30:
            msg = random.choice([
                "Длинновато для клички — можно покороче?",
                "Давайте основное имя, без титулов.",
            ])
            return _make_response(msg, OnboardingState.PET_INTRO, user_flags, pet_profile)

        # Digits or special chars only
        if not re.search(r'[a-zA-Zа-яА-ЯёЁ]', pet_name):
            msg = random.choice([
                "Хм, это кличка? Как зовут питомца?",
                "Не совсем понял — как зовут вашего питомца?",
            ])
            return _make_response(msg, OnboardingState.PET_INTRO, user_flags, pet_profile)

        # Stop-word — ask for confirmation
        if name_lower in _PET_NAME_STOP_WORDS:
            user_flags["_pet_name_pending"] = pet_name
            msg = f'Его правда зовут "{pet_name}"? Просто уточняю.'
            return _make_response(
                msg, OnboardingState.PET_INTRO, user_flags, pet_profile,
                quick_replies=["Да", "Нет"],
            )

        message = f"{pet_name} — запомнил."
    else:
        message = "Записал, спасибо! Уточню пару деталей"

    return _make_response(
        message, OnboardingState.SPECIES_CLARIFY, user_flags, pet_profile,
        auto_follow=True,
    )


def _handle_species_clarify(user_input, pet_profile, user_flags):
    species_raw = user_input.strip().lower()
    user_flags["species"] = species_raw

    pet_name = user_flags.get("pet_name", "ваш питомец")
    message = f"{pet_name} — кот или кошка? Или собака?"
    return _make_response(
        message, OnboardingState.PASSPORT_OFFER, user_flags, pet_profile,
        quick_replies=["Кот", "Кошка", "Собака"],
        input_type="quick_reply",
    )


def _handle_passport_offer(user_input, pet_profile, user_flags):
    pet_name = user_flags.get("pet_name", "вашего питомца")
    message = (
        f"У {_decline_name(pet_name, 'gen')} есть ветеринарный паспорт?\n"
        "Если есть — сфотографируйте, я прочитаю его и заполню карточку "
        "автоматически. Займёт секунд 30."
    )
    return _make_response(
        message, OnboardingState.BREED, user_flags, pet_profile,
        quick_replies=["Да, сфотографирую", "Нет, расскажу сам", "Не знаю где он"],
        input_type="quick_reply",
    )


def _handle_passport_ocr(user_input, pet_profile, user_flags):
    message = (
        "Сфотографируйте главную страницу паспорта — "
        "ту где основные данные о питомце.\n"
        "Можно чуть под углом, главное чтобы текст был виден."
    )
    return _make_response(
        message, OnboardingState.BREED, user_flags, pet_profile,
        input_type="image",
    )


def _handle_breed(user_input, pet_profile, user_flags):
    pet_name = user_flags.get("pet_name", "питомца")

    # ── First call — show the question ──
    if not user_input or not user_input.strip():
        message = (
            f"Какой породы {_decline_name(pet_name, 'acc')}?\n"
            "Это поможет мне давать точные советы — у каждой породы свои нюансы."
        )
        return _make_response(
            message, OnboardingState.BREED, user_flags, pet_profile,
            quick_replies=["Не знаю породу", "Дворняга или метис"],
        )

    raw = user_input.strip()
    raw_lower = raw.lower()

    # ── Confirmation flow: user confirming a breed suggestion ──
    if user_flags.get("_breed_pending"):
        pending = user_flags.pop("_breed_pending")
        if raw_lower in ("да", "да, верно", "верно", "ок", "угу", "ага", "правильно"):
            user_flags["breed"] = pending
            user_flags["breed_confirmed"] = True
            return _make_response(
                "Записал!", OnboardingState.BREED_INSIGHT, user_flags, pet_profile,
                auto_follow=True,
            )
        elif raw_lower in ("нет, другая порода", "нет", "другая"):
            return _make_response(
                random.choice([
                    "Напишите породу — постараюсь найти.",
                    "Хорошо — напишите как можно точнее, найду в базе.",
                ]),
                OnboardingState.BREED, user_flags, pet_profile,
            )
        elif raw_lower in ("введу сам", "ввести вручную"):
            return _make_response(
                random.choice([
                    "Введите название породы — я проверю.",
                    "Хорошо — напишите как можно точнее, найду в базе.",
                ]),
                OnboardingState.BREED, user_flags, pet_profile,
            )
        # Anything else — treat as new breed input, fall through

    # ── Mixed breed confirmation flow ──
    if user_flags.get("_breed_mixed_pending"):
        user_flags.pop("_breed_mixed_pending")
        if raw_lower in ("да", "да, верно", "верно", "ок", "угу", "ага"):
            user_flags["breed"] = "беспородный (метис)"
            user_flags["breed_confirmed"] = True
            return _make_response(
                "Записал!", OnboardingState.BREED_INSIGHT, user_flags, pet_profile,
                auto_follow=True,
            )
        elif raw_lower in ("нет, есть порода", "нет", "есть порода"):
            return _make_response(
                random.choice([
                    "Напишите породу — постараюсь найти.",
                    "Хорошо — напишите как можно точнее, найду в базе.",
                ]),
                OnboardingState.BREED, user_flags, pet_profile,
            )
        # Anything else — treat as new breed input, fall through

    # ── "Не знаю породу" — skip breed ──
    if raw_lower in ("не знаю породу", "не знаю", "хз", "без понятия"):
        user_flags["breed"] = None
        return _make_response(
            "Записал!", OnboardingState.BREED_INSIGHT, user_flags, pet_profile,
            auto_follow=True,
        )

    # ── "Сфотографирую" — redirect to photo ──
    if "сфотографирую" in raw_lower or "сфотографирую питомца" in raw_lower:
        return _make_response(
            "Отправьте фото — попробую определить породу.",
            OnboardingState.BREED, user_flags, pet_profile,
            input_type="image",
        )

    # ── Scenario 6: Mixed breed / дворняга ──
    if raw_lower in _MIXED_BREED_KEYWORDS or any(kw in raw_lower for kw in _MIXED_BREED_KEYWORDS):
        user_flags["_breed_mixed_pending"] = True
        msg = random.choice([
            "Дворняги — отдельная гордость. Запишу как беспородный (метис). Все верно?",
            "Понял — беспородный. Это честно и это нормально. Подтверждаете?",
            "Метис — записал. Верно?",
        ])
        return _make_response(
            msg, OnboardingState.BREED, user_flags, pet_profile,
            quick_replies=["Да, верно", "Нет, есть порода"],
        )

    # ── Off-topic detection (free text only) ──
    msg_type = classify_onboarding_message(user_input, OnboardingState.BREED.value)
    off_topic = _handle_off_topic(msg_type, user_input, OnboardingState.BREED, user_flags, pet_profile)
    if off_topic:
        return off_topic

    # ── Exact case-insensitive match ──
    if raw_lower in _ALL_BREEDS_LOWER:
        # Find the original-cased version
        exact = next(b for b in ALL_BREEDS if b.lower() == raw_lower)
        user_flags["breed"] = exact
        user_flags["breed_confirmed"] = True
        return _make_response(
            "Записал!", OnboardingState.BREED_INSIGHT, user_flags, pet_profile,
            auto_follow=True,
        )

    # ── Substring / prefix match (e.g. "йорк" → "Йоркширский терьер") ──
    prefix_matches = [b for b in ALL_BREEDS if b.lower().startswith(raw_lower)]
    if not prefix_matches and len(raw_lower) >= 3:
        # Check if input is a substring of any breed name
        prefix_matches = [b for b in ALL_BREEDS if raw_lower in b.lower()]

    if len(prefix_matches) == 1:
        user_flags["_breed_pending"] = prefix_matches[0]
        msg = random.choice([
            f"Имеете в виду {prefix_matches[0]}?",
            f"Похоже на {prefix_matches[0]} — верно?",
        ])
        return _make_response(
            msg, OnboardingState.BREED, user_flags, pet_profile,
            quick_replies=["Да, верно", "Нет, другая порода", "Введу сам"],
        )

    if len(prefix_matches) >= 2:
        top3 = prefix_matches[:3]
        msg = random.choice([
            "Нашёл несколько похожих пород — какая из них?",
            "Уточните породу — нашёл несколько вариантов:",
            "Таких пород несколько — выберите точную:",
        ])
        return _make_response(
            msg, OnboardingState.BREED, user_flags, pet_profile,
            quick_replies=top3 + ["Другая"],
        )

    # ── Fuzzy search (WRatio handles partial matches well) ──
    matches = process.extract(
        raw_lower, ALL_BREEDS, scorer=fuzz.WRatio, limit=5,
    )
    # matches: list of (breed_name, score, index)

    best_name, best_score = (matches[0][0], matches[0][1]) if matches else ("", 0)

    # ── Scenario 3: Near-exact match (score >= 90) ──
    if best_score >= 90:
        # Check if multiple breeds have similar high scores
        top_tier = [m for m in matches if m[1] >= best_score - 5]
        if len(top_tier) >= 2:
            # Multiple equally good matches — ask user to pick
            top3 = [m[0] for m in top_tier[:3]]
            msg = random.choice([
                "Нашёл несколько похожих пород — какая из них?",
                "Уточните породу — нашёл несколько вариантов:",
            ])
            return _make_response(
                msg, OnboardingState.BREED, user_flags, pet_profile,
                quick_replies=top3 + ["Другая"],
            )
        user_flags["breed"] = best_name
        user_flags["breed_confirmed"] = True
        return _make_response(
            "Записал!", OnboardingState.BREED_INSIGHT, user_flags, pet_profile,
            auto_follow=True,
        )

    # ── Noise filter: WRatio can be generous for unrelated words ──
    # Confirm with strict ratio — if strict match is very low, it's noise
    strict_score = fuzz.ratio(raw_lower, best_name.lower())
    if best_score < 60 or (best_score < 75 and strict_score < 40):
        msg = random.choice([
            "Это не совсем порода. Знаете как она называется?",
            "Хм, не понял породу. Знаете точное название?",
            "Не распознал породу — попробуйте написать иначе или сфотографируйте питомца.",
        ])
        return _make_response(
            msg, OnboardingState.BREED, user_flags, pet_profile,
            quick_replies=["Не знаю породу", "Сфотографирую питомца", "Дворняга или метис"],
        )

    # Gap filter: keep only matches within 12 points of the best
    relevant = [m for m in matches if m[1] >= best_score - 12 and m[1] >= 60]

    # ── Scenario 2: Single clear winner (typo or abbreviation) ──
    if len(relevant) == 1:
        user_flags["_breed_pending"] = best_name
        msg = random.choice([
            f"Не нашёл такую породу — может быть {best_name}?",
            f"Похоже на опечатку — имеете в виду {best_name}?",
            f"Не совсем понял породу — вы имели в виду {best_name}?",
        ])
        return _make_response(
            msg, OnboardingState.BREED, user_flags, pet_profile,
            quick_replies=["Да, верно", "Нет, другая порода", "Введу сам"],
        )

    # ── Scenario 1: Multiple similar breeds ──
    top3 = [m[0] for m in relevant[:3]]
    msg = random.choice([
        "Нашёл несколько похожих пород — какая из них?",
        "Уточните породу — нашёл несколько вариантов:",
        "Таких пород несколько — выберите точную:",
    ])
    return _make_response(
        msg, OnboardingState.BREED, user_flags, pet_profile,
        quick_replies=top3 + ["Другая"],
    )


def _handle_breed_insight(user_input, pet_profile, user_flags):
    breed = user_flags.get("breed")
    pet_name = user_flags.get("pet_name", "питомца")

    if breed and breed != "беспородный (метис)":
        # Gemini breed insight
        insight = generate_breed_insight(breed, pet_name)
        if insight:
            message = insight
        else:
            # Fallback if Gemini fails
            message = f"{breed} — буду учитывать особенности породы."
    elif breed == "беспородный (метис)":
        message = (
            "Дворняги, как правило, здоровее породистых — "
            "меньше генетических рисков. Хорошая новость."
        )
    else:
        message = "Хорошо, двигаемся дальше."

    return _make_response(
        message, OnboardingState.AGE, user_flags, pet_profile,
        auto_follow=True,
    )


def _handle_age(user_input, pet_profile, user_flags):
    # First call (from breed_insight auto_follow) — show the question
    if not user_input or not user_input.strip():
        pet_name = user_flags.get("pet_name", "вашего питомца")
        message = (
            f"Когда у {_decline_name(pet_name, 'dat')} день рождения?\n"
            "Не только поздравлю — буду знать когда подходит время прививок, "
            "плановых осмотров и когда переходить на корм для взрослых."
        )
        return _make_response(
            message, OnboardingState.AGE, user_flags, pet_profile,
            quick_replies=["Введу дату", "Полных лет", "Не знаю"],
        )

    user_flags["age_raw"] = user_input
    age_raw = user_input.strip().lower()

    # ── "Не знаю" — skip age, proceed ──
    if age_raw in ("не знаю", "не помню", "хз", "без понятия"):
        user_flags["age_years"] = None
        user_flags["birth_date"] = None
        return _age_next_state(user_flags, pet_profile)

    # ── Off-topic detection (free text, not dates/numbers/keywords) ──
    is_date = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', user_input.strip())
    has_number = re.search(r'\d', age_raw)
    if not is_date and not has_number:
        msg_type = classify_onboarding_message(user_input, OnboardingState.AGE.value)
        off_topic = _handle_off_topic(msg_type, user_input, OnboardingState.AGE, user_flags, pet_profile)
        if off_topic:
            return off_topic

    # ── ISO date YYYY-MM-DD (from DatePicker) ──
    iso_match = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', user_input.strip())
    if iso_match:
        try:
            birth = date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            return _make_response(
                "Некорректная дата — попробуйте ещё раз.",
                OnboardingState.AGE, user_flags, pet_profile,
                quick_replies=["Введу дату", "Полных лет", "Не знаю"],
            )

        today = date.today()
        if birth > today:
            msg = random.choice([
                "Дата в будущем — проверьте и попробуйте ещё раз.",
                "Похоже дата ещё не наступила — уточните?",
            ])
            return _make_response(
                msg, OnboardingState.AGE, user_flags, pet_profile,
                quick_replies=["Введу дату", "Полных лет", "Не знаю"],
            )

        age_years = (today - birth).days / 365.25
        user_flags["birth_date"] = user_input.strip()
        user_flags["age_years"] = round(age_years, 1)
        return _age_next_state(user_flags, pet_profile)

    # ── Fractional number (e.g. "0.5", "1.5") ──
    frac_match = re.match(r'^(\d+)[.,](\d+)\s*$', age_raw)
    if frac_match:
        msg = random.choice([
            "Дробный возраст сложно записать — сколько полных месяцев?",
            "Лучше скажите в месяцах — так точнее будет.",
        ])
        return _make_response(msg, OnboardingState.AGE, user_flags, pet_profile)

    # ── Extract number ──
    nums = re.findall(r'\d+', age_raw)
    if nums:
        age = int(nums[0])

        if age > 30:
            msg = random.choice([
                f"{age} — это рекорд! Наверное имеешь в виду {age // 10} или {age % 10}?",
                f"{age} лет? Уточните возраст — кажется, что-то не так.",
            ])
            return _make_response(msg, OnboardingState.AGE, user_flags, pet_profile)

        if age == 0:
            msg = random.choice([
                "Совсем кроха! Сколько месяцев примерно?",
                "Малыш! Напишите возраст в месяцах.",
            ])
            return _make_response(msg, OnboardingState.AGE, user_flags, pet_profile)

        user_flags["age_years"] = age
        return _age_next_state(user_flags, pet_profile)

    # ── No number found ──
    msg = random.choice([
        "Не разобрал возраст — напишите цифрой, например: 3",
        "Напишите возраст цифрой — например, 2 или 5.",
    ])
    return _make_response(msg, OnboardingState.AGE, user_flags, pet_profile)


def _age_next_state(user_flags, pet_profile):
    """After successful age parsing — determine next state based on species."""
    species = user_flags.get("species", "")
    if species == "кот":
        user_flags["gender"] = "самец"
        next_state = OnboardingState.NEUTERED
    elif species == "кошка":
        user_flags["gender"] = "самка"
        next_state = OnboardingState.NEUTERED
    else:
        next_state = OnboardingState.GENDER

    return _make_response("Записал!", next_state, user_flags, pet_profile)


def _handle_gender(user_input, pet_profile, user_flags):
    raw = user_input.strip().lower()
    if "самец" in raw or "мальчик" in raw:
        user_flags["gender"] = "самец"
    elif "самка" in raw or "девочка" in raw:
        user_flags["gender"] = "самка"
    else:
        user_flags["gender"] = raw

    pet_name = user_flags.get("pet_name", "ваш питомец")
    message = (
        f"{pet_name} — мальчик или девочка?\n"
        "Это важно для правильных советов по здоровью."
    )
    return _make_response(
        message, OnboardingState.NEUTERED, user_flags, pet_profile,
        quick_replies=["Мальчик", "Девочка"],
        input_type="quick_reply",
    )


def _handle_neutered(user_input, pet_profile, user_flags):
    pet_name = user_flags.get("pet_name", "ваш питомец")
    gender = user_flags.get("gender", "")

    # First call — show the question
    if not user_input:
        if gender == "самец":
            message = (
                f"{pet_name} кастрирован?\n"
                "Это важно — влияет на питание и медицинские рекомендации, "
                "хочу давать вам точные советы."
            )
        else:
            message = (
                f"{pet_name} стерилизована?\n"
                "Это важно — влияет на питание и медицинские рекомендации, "
                "хочу давать вам точные советы."
            )
        return _make_response(
            message, OnboardingState.NEUTERED, user_flags, pet_profile,
            quick_replies=["Да", "Нет", "Не знаю"],
            input_type="quick_reply",
        )

    # Process answer
    low = user_input.strip().lower()
    if low in ("да", "кастрирован", "стерилизована", "стерилизован"):
        user_flags["neutered"] = True
    elif low in ("нет", "не кастрирован", "не стерилизована"):
        user_flags["neutered"] = False
    elif low in ("не знаю", "не помню", "хз"):
        user_flags["neutered"] = None
    else:
        # Repeat the question
        word = "кастрирован" if gender == "самец" else "стерилизована"
        return _make_response(
            f"Так {pet_name} {word} или нет?",
            OnboardingState.NEUTERED, user_flags, pet_profile,
            quick_replies=["Да", "Нет", "Не знаю"],
            input_type="quick_reply",
        )

    return _make_response(
        "", OnboardingState.PHOTO_AVATAR, user_flags, pet_profile,
        auto_follow=True,
    )


def _handle_photo_avatar(user_input, pet_profile, user_flags):
    pet_name = user_flags.get("pet_name", "питомца")
    message = (
        f"Добавьте фото {_decline_name(pet_name, 'gen')} для карточки.\n"
        "Так его будет легко узнать, и карточка станет живой — "
        "не просто данные, а настоящий профиль.\n"
        "Подойдёт любое фото."
    )
    return _make_response(
        message, OnboardingState.CONFIRM_SUMMARY, user_flags, pet_profile,
        quick_replies=["Загрузить фото", "Пропустить пока"],
        input_type="quick_reply",
    )


def _handle_confirm_summary(user_input, pet_profile, user_flags):
    pet_name = user_flags.get("pet_name", "Питомец")
    species = user_flags.get("species", "")
    breed = user_flags.get("breed", "")
    age = user_flags.get("age_years", "")
    gender = user_flags.get("gender", "")
    neutered = user_flags.get("neutered")

    species_text = {"кот": "Кот", "кошка": "Кошка", "собака": "Собака"}.get(species, species)
    neutered_text = "Да" if neutered is True else ("Нет" if neutered is False else "Не указано")
    gender_text = "Самец" if gender == "самец" else ("Самка" if gender == "самка" else "")

    message = "Я записал всё как вы рассказали. Проверьте:\n\nВсё верно?"

    card = {
        "name": pet_name,
        "species": species_text,
        "breed": breed or "не указана",
        "gender": gender_text or "не указан",
        "age": f"{age} лет" if age else "не указан",
        "neutered": neutered_text,
        "avatar_url": user_flags.get("avatar_url"),
    }

    return _make_response(
        message, OnboardingState.COMPLETE, user_flags, pet_profile,
        quick_replies=["Всё верно", "Нужно исправить"],
        pet_card=card,
    )


def _handle_complete(user_input, pet_profile, user_flags):
    pet_name = user_flags.get("pet_name", "питомец")
    owner_name = user_flags.get("owner_name", "")
    message = (
        f"Карточка {_decline_name(pet_name, 'gen')} готова.\n"
        f"{owner_name}, я рядом — спрашивайте всё что угодно: здоровье, питание, "
        "прививки или просто если что-то покажется странным."
    )
    return _make_response(
        message, OnboardingState.COMPLETE, user_flags, pet_profile,
        quick_replies=[
            "Когда нужны прививки?",
            "Чем лучше кормить?",
            "Добавить данные в карточку",
            "Задать вопрос по здоровью",
        ],
    )


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
    greeting_prefix: str | None = None,
) -> dict:
    """Entry point called from chat.py:322."""
    user_flags = get_user_flags(user_id)
    state = get_current_state(user_flags)

    # Greeting for returning user (5h+ cooldown)
    if greeting_prefix:
        if state == OnboardingState.WELCOME:
            # First visit or fresh start — pass to _handle_welcome
            user_flags["_greeting_prefix"] = greeting_prefix
        elif state != OnboardingState.COMPLETE:
            # Mid-onboarding return — greet and offer to continue
            owner_name = user_flags.get("owner_name", "")
            pet_name = user_flags.get("pet_name", "питомцем")
            message = (
                f"{greeting_prefix}, {owner_name}.\n"
                f"Продолжим знакомиться с {pet_name}?"
            )
            return _make_response(
                message, state, user_flags, pet_profile,
                quick_replies=["Да, продолжим", "Начать заново"],
            )

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
            "pet_id": None,
            "pet_name": user_flags.get("pet_name"),
            "user_flags": {},
        }

    result = route_state(state, message_text, pet_profile, user_flags)
    next_state = OnboardingState(result["onboarding_step"])

    # Пропускать состояния если данные уже известны
    skip = set(user_flags.get("onboarding_skip", []))
    while next_state.value in skip and next_state != OnboardingState.COMPLETE:
        next_state = TRANSITIONS.get(next_state, OnboardingState.COMPLETE)

    result["onboarding_step"] = next_state.value
    result["next_question"] = next_state.value

    # Persist new state
    set_state(user_flags, next_state)
    update_user_flags(user_id, user_flags)

    # On COMPLETE: create pet + update user + bind chat history
    if next_state == OnboardingState.COMPLETE:
        pet_id_created = _create_pet_from_flags(user_id, user_flags, supabase_client)

        # Привязываем онбординг-историю (pet_id=NULL) к созданному питомцу
        if pet_id_created:
            try:
                supabase_client.table("chat").update(
                    {"pet_id": pet_id_created}
                ).eq("user_id", user_id).is_("pet_id", "null").execute()
            except Exception:
                pass  # не блокируем финал если привязка не удалась

        update_data = {"is_onboarded": True}
        owner_name = user_flags.get("owner_name")
        if owner_name:
            update_data["owner_name"] = owner_name

        supabase_client.table("users").update(update_data).eq("id", user_id).execute()

        result["pet_id"] = pet_id_created

    return result
