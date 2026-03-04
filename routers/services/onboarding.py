"""
routers/services/onboarding.py — Deterministic onboarding engine.

Pure logic, no IO, no LLM, no Supabase.
Three public functions:
  - get_onboarding_message(step, pet_profile) → dict
  - validate_onboarding_input(step, user_message, pet_profile) → dict
  - is_off_topic(step, user_message) → bool
"""

import random
import re
from datetime import datetime, timedelta

# ── Step order ────────────────────────────────────────────────────────────────

REQUIRED_STEPS = [
    "species", "name", "name_reaction", "gender", "neutered",
    "age_choice", "age_date", "age_approx",
]
OPTIONAL_STEPS = [
    "breed", "color", "features",
    "chip_id_ask", "chip_id_input", "stamp_id_ask", "stamp_id_input",
]

# ── Name extraction helpers ───────────────────────────────────────────────────

_NAME_STOP_WORDS = {
    "его", "её", "ее", "зовут", "кличка", "имя", "это", "мой", "моя", "моё",
    "мое", "наш", "наша", "наше", "у", "меня", "нас", "питомец", "питомца",
    "кот", "кошка", "собака", "пёс", "пес", "щенок", "котёнок", "котенок",
    "котик", "кошечка", "собачка", "пёсик", "песик",
}

_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]{1,19}$")


def _extract_name(text: str) -> str | None:
    """Extract a pet name from user text, stripping stop words."""
    words = text.strip().split()
    candidates = [w for w in words if w.lower() not in _NAME_STOP_WORDS]
    if not candidates:
        return None
    # Take the last candidate (often the actual name after "его зовут ...")
    raw = candidates[-1].strip(".,!?;:")
    # Capitalize first letter
    if raw:
        raw = raw[0].upper() + raw[1:]
    if _NAME_RE.match(raw):
        return raw
    return None


# ── get_onboarding_message ────────────────────────────────────────────────────

def get_onboarding_message(step: str, pet_profile: dict) -> dict:
    """Return deterministic message + buttons for the given onboarding step."""

    _name = pet_profile.get("name") or "питомец"
    _species = pet_profile.get("species") or ""
    _gender = pet_profile.get("gender") or ""

    if step == "species":
        return {
            "text": "Расскажи, кто у тебя?",
            "quick_replies": ["Кот/кошка 🐱", "Собака 🐶"],
            "input_type": "buttons",
        }

    if step == "name":
        return {
            "text": "Расскажи — как зовут?",
            "quick_replies": [],
            "input_type": "text",
        }

    if step == "name_reaction":
        _reactions = [
            "Классное имя!",
            "Отличное имя!",
            "Красивое имя!",
            "Звучит здорово!",
            "Хорошее имя!",
        ]
        return {
            "text": random.choice(_reactions),
            "quick_replies": [],
            "input_type": "none",
        }

    if step == "gender":
        if _species == "cat":
            return {
                "text": f"{_name} — кот или кошка?",
                "quick_replies": ["Кот", "Кошка"],
                "input_type": "buttons",
            }
        else:
            return {
                "text": f"{_name} — мальчик или девочка?",
                "quick_replies": ["Мальчик", "Девочка"],
                "input_type": "buttons",
            }

    if step == "neutered":
        if _gender == "male":
            text = f"{_name} кастрирован?"
        elif _gender == "female":
            text = f"{_name} стерилизована?"
        else:
            text = f"{_name} кастрирован(а)?"
        return {
            "text": text,
            "quick_replies": ["Да", "Нет", "Не знаю"],
            "input_type": "buttons",
        }

    if step == "age_choice":
        return {
            "text": f"Знаешь дату рождения {_name}?",
            "quick_replies": ["Да, знаю", "Нет, примерно"],
            "input_type": "buttons",
        }

    if step == "age_date":
        return {
            "text": f"Выбери дату рождения {_name}",
            "quick_replies": [],
            "input_type": "date_picker",
        }

    if step == "age_approx":
        return {
            "text": f"Сколько примерно {_name} лет?",
            "quick_replies": [],
            "input_type": "text",
        }

    if step == "optional_gate":
        return {
            "text": f"Профиль {_name} готов! Можем добавить подробности — порода, окрас, приметы — или вернёмся к этому позже",
            "quick_replies": ["Заполним сейчас", "Позже"],
            "input_type": "buttons",
        }

    if step == "breed":
        return {
            "text": f"Какой породы {_name}?",
            "quick_replies": ["Не знаю / Метис"],
            "input_type": "text",
        }

    if step == "color":
        return {
            "text": f"Какого окраса {_name}?",
            "quick_replies": ["Пропустить"],
            "input_type": "text",
        }

    if step == "features":
        return {
            "text": f"Есть ли у {_name} особые приметы — пятна, шрамы, необычный окрас?",
            "quick_replies": ["Нет", "Пропустить"],
            "input_type": "text",
        }

    if step == "chip_id_ask":
        return {
            "text": f"Есть ли у {_name} микрочип?",
            "quick_replies": ["Да", "Нет", "Не знаю"],
            "input_type": "buttons",
        }

    if step == "chip_id_input":
        return {
            "text": "Напиши номер чипа (15 цифр)",
            "quick_replies": [],
            "input_type": "text",
        }

    if step == "stamp_id_ask":
        return {
            "text": f"Есть ли у {_name} клеймо?",
            "quick_replies": ["Да", "Нет", "Не знаю"],
            "input_type": "buttons",
        }

    if step == "stamp_id_input":
        return {
            "text": "Напиши номер клейма",
            "quick_replies": [],
            "input_type": "text",
        }

    # Unknown step fallback
    return {"text": "", "quick_replies": [], "input_type": "none"}


# ── validate_onboarding_input ─────────────────────────────────────────────────

def validate_onboarding_input(step: str, user_message: str, pet_profile: dict) -> dict:
    """Parse and validate user's answer for the given onboarding step."""

    _msg = user_message.strip()
    _msg_lower = _msg.lower()
    _name = pet_profile.get("name") or "питомец"

    ok = {"valid": True, "parsed_value": None, "field_updates": {}, "error_message": None, "next_step": None}
    fail = {"valid": False, "parsed_value": None, "field_updates": {}, "error_message": None, "next_step": None}

    # ── species ───────────────────────────────────────────────────────────
    if step == "species":
        if _msg == "Кот/кошка 🐱" or any(k in _msg_lower for k in ("кот", "кошк", "кис")):
            return {**ok, "parsed_value": "cat", "field_updates": {"species": "cat"}}
        if _msg == "Собака 🐶" or any(k in _msg_lower for k in ("собак", "пёс", "пес", "щен")):
            return {**ok, "parsed_value": "dog", "field_updates": {"species": "dog"}}
        return {
            **fail,
            "error_message": "Пока я умею помогать только с кошками и собаками, но я учусь! Расскажи, кто у тебя?",
        }

    # ── name ──────────────────────────────────────────────────────────────
    if step == "name":
        _raw = user_message.strip()

        # Стоп-фразы которые точно НЕ имя
        _stop_phrases = [
            "привет", "здравствуй", "добрый", "доброе", "добрый день",
            "добрый вечер", "доброе утро", "здрасте", "хай", "hello", "hi",
        ]
        if _msg_lower in _stop_phrases:
            return {**fail, "error_message": "Напиши просто кличку питомца"}

        # Убираем вводные слова
        _intro_patterns = [
            "его зовут ", "её зовут ", "ее зовут ", "зовут ",
            "кличка ", "имя ", "это ",
            "моего кота зовут ", "мою кошку зовут ", "мою собаку зовут ",
            "моего пса зовут ", "мою собачку зовут ",
        ]
        _cleaned = _raw
        for p in _intro_patterns:
            if _cleaned.lower().startswith(p):
                _cleaned = _cleaned[len(p):].strip()
                break

        # Берём первое слово как кличку
        _words = _cleaned.split()
        if not _words:
            return {**fail, "error_message": "Хм, не совсем понял. Напиши просто кличку"}

        _candidate = _words[0].strip(".,!?;:")

        # Валидация: 2-20 символов, только буквы и дефис
        if len(_candidate) < 2 or len(_candidate) > 20:
            return {**fail, "error_message": "Хм, не совсем понял. Напиши просто кличку"}
        if not all(c.isalpha() or c == "-" for c in _candidate):
            return {**fail, "error_message": "Хм, не совсем понял. Напиши просто кличку"}

        # Capitalize
        _name = _candidate[0].upper() + _candidate[1:]

        return {**ok, "parsed_value": _name, "field_updates": {"name": _name}}

    # ── name_reaction (no user input expected) ────────────────────────────
    if step == "name_reaction":
        return ok

    # ── gender ────────────────────────────────────────────────────────────
    if step == "gender":
        if any(k in _msg_lower for k in ("кот", "мальчик", "самец")) or _msg_lower == "м":
            return {**ok, "parsed_value": "male", "field_updates": {"gender": "male"}}
        if any(k in _msg_lower for k in ("кошка", "девочка", "самка")) or _msg_lower == "ж":
            return {**ok, "parsed_value": "female", "field_updates": {"gender": "female"}}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── neutered ──────────────────────────────────────────────────────────
    if step == "neutered":
        if any(k in _msg_lower for k in ("да", "кастрир", "стерил")):
            return {**ok, "parsed_value": True, "field_updates": {"neutered": True}}
        if _msg_lower == "нет":
            return {**ok, "parsed_value": False, "field_updates": {"neutered": False}}
        if "не знаю" in _msg_lower:
            return {**ok, "parsed_value": None, "field_updates": {"neutered_skipped": True}, "next_step": "age_choice"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── age_choice ────────────────────────────────────────────────────────
    if step == "age_choice":
        if any(k in _msg_lower for k in ("да", "знаю")):
            return {**ok, "next_step": "age_date"}
        if any(k in _msg_lower for k in ("нет", "примерно")):
            return {**ok, "next_step": "age_approx"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── age_date ──────────────────────────────────────────────────────────
    if step == "age_date":
        try:
            parsed_date = datetime.strptime(_msg[:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            return {**fail, "error_message": "Дата должна быть не в будущем и не старше 30 лет"}
        today = datetime.now().date()
        min_date = today - timedelta(days=30 * 365)
        if parsed_date > today or parsed_date < min_date:
            return {**fail, "error_message": "Дата должна быть не в будущем и не старше 30 лет"}
        return {**ok, "parsed_value": str(parsed_date), "field_updates": {"birth_date": str(parsed_date)}}

    # ── age_approx ────────────────────────────────────────────────────────
    if step == "age_approx":
        _species = pet_profile.get("species", "")
        nums = re.findall(r"\d+", _msg)
        if not nums:
            return {**fail, "error_message": "Напиши число — сколько лет или месяцев"}

        val = int(nums[0])
        is_months = "мес" in _msg_lower

        if is_months:
            age_years = round(val / 12, 1)
        else:
            age_years = val

        if age_years == 0 and not is_months:
            return {**fail, "error_message": f"Совсем малыш! Сколько {_name} месяцев?"}

        max_age = 25 if _species == "cat" else 20
        if age_years > max_age:
            return {**fail, "error_message": f"{_name} правда столько? Напиши ещё раз, чтобы я точно не ошибся"}

        return {**ok, "parsed_value": age_years, "field_updates": {"age_years": age_years}}

    # ── optional_gate ─────────────────────────────────────────────────────
    if step == "optional_gate":
        if any(k in _msg_lower for k in ("заполн", "сейчас", "давай", "да")):
            return {**ok, "next_step": "breed"}
        if any(k in _msg_lower for k in ("позже", "потом", "нет", "пропуст")):
            return {**ok, "next_step": "complete"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── breed ─────────────────────────────────────────────────────────────
    if step == "breed":
        if any(k in _msg_lower for k in ("не знаю", "метис", "дворняг", "дворняж")):
            return {**ok, "parsed_value": "метис", "field_updates": {"breed": "метис"}}
        if len(_msg.strip()) < 2:
            return {**fail, "error_message": "Напиши породу или выбери «Не знаю / Метис»"}
        return {**ok, "parsed_value": _msg.strip(), "field_updates": {"breed": _msg.strip()}}

    # ── color ─────────────────────────────────────────────────────────────
    if step == "color":
        if any(k in _msg_lower for k in ("пропуст", "skip")):
            return {**ok, "parsed_value": None, "field_updates": {}, "next_step": "features"}
        if len(_msg.strip()) < 2:
            return {**fail, "error_message": "Опиши окрас или нажми «Пропустить»"}
        return {**ok, "parsed_value": _msg.strip(), "field_updates": {"color": _msg.strip()}}

    # ── features ──────────────────────────────────────────────────────────
    if step == "features":
        if any(k in _msg_lower for k in ("нет", "пропуст", "skip")):
            return {**ok, "parsed_value": None, "field_updates": {}}
        return {**ok, "parsed_value": _msg.strip(), "field_updates": {"features": _msg.strip()}}

    # ── chip_id_ask ───────────────────────────────────────────────────────
    if step == "chip_id_ask":
        if _msg_lower in ("да",) or _msg_lower.startswith("да"):
            return {**ok, "next_step": "chip_id_input"}
        if any(k in _msg_lower for k in ("нет", "не знаю")):
            return {**ok, "field_updates": {"chip_skipped": True}, "next_step": "stamp_id_ask"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── chip_id_input ─────────────────────────────────────────────────────
    if step == "chip_id_input":
        digits = re.sub(r"\D", "", _msg)
        if len(digits) == 15:
            return {**ok, "parsed_value": digits, "field_updates": {"chip_id": digits}}
        return {**fail, "error_message": "Номер чипа — это 15 цифр без букв. Проверь и напиши ещё раз"}

    # ── stamp_id_ask ──────────────────────────────────────────────────────
    if step == "stamp_id_ask":
        if _msg_lower in ("да",) or _msg_lower.startswith("да"):
            return {**ok, "next_step": "stamp_id_input"}
        if any(k in _msg_lower for k in ("нет", "не знаю")):
            return {**ok, "field_updates": {"stamp_skipped": True}, "next_step": "complete"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── stamp_id_input ────────────────────────────────────────────────────
    if step == "stamp_id_input":
        cleaned = re.sub(r"\s", "", _msg)
        if re.match(r"^[A-Za-zА-Яа-яЁё0-9]{3,8}$", cleaned):
            return {**ok, "parsed_value": cleaned.upper(), "field_updates": {"stamp_id": cleaned.upper()}}
        return {**fail, "error_message": "Обычно клеймо — это несколько букв и цифр. Проверь и напиши ещё раз"}

    # ── unknown step ──────────────────────────────────────────────────────
    return ok


# ── is_off_topic ──────────────────────────────────────────────────────────────

# Precompute button sets per step for fast lookup
_BUTTON_MAP: dict[str, set[str]] = {}
for _s in REQUIRED_STEPS + OPTIONAL_STEPS + ["optional_gate"]:
    _m = get_onboarding_message(_s, {})
    if _m["quick_replies"]:
        _BUTTON_MAP[_s] = {b.lower() for b in _m["quick_replies"]}

_QUESTION_WORDS = ("как ", "что ", "чем ", "зачем", "почему", "можно", "стоит", "а чем", "а как")


def is_off_topic(step: str, user_message: str) -> bool:
    """Check if user's message is off-topic for the current onboarding step."""
    _msg = user_message.strip()
    _msg_lower = _msg.lower()

    # Exact button match → on-topic
    if step in _BUTTON_MAP and _msg_lower in _BUTTON_MAP[step]:
        return False

    # Name step: 1-3 words with a capitalized word → on-topic
    if step == "name":
        words = _msg.split()
        if 1 <= len(words) <= 3 and any(w[0].isupper() for w in words if w):
            return False

    # Age approx: contains a digit → on-topic
    if step == "age_approx" and re.search(r"\d", _msg):
        return False

    # Question words + "?" → off-topic question
    if "?" in _msg and any(_msg_lower.startswith(qw) or f" {qw}" in _msg_lower for qw in _QUESTION_WORDS):
        return True

    # Long message with "?" → likely a question
    if len(_msg) > 50 and "?" in _msg:
        return True

    # Fallback: assume on-topic
    return False
