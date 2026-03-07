"""
routers/services/onboarding.py — Deterministic onboarding engine v5.

Pure logic, no IO, no LLM, no Supabase.
Two-stage onboarding with passport support.

Public functions:
  - get_onboarding_message(step, pet_profile) → dict
  - validate_onboarding_input(step, user_message, pet_profile) → dict
  - is_off_topic(step, user_message) → bool
  - get_previous_step(current_step, pet_profile) → str | None
"""

import re
from datetime import datetime, timedelta

# ── Step definitions ─────────────────────────────────────────────────────────

STAGE_1_STEPS = [
    "owner_name", "pet_count", "species", "name", "passport_entry",
    # passport branch: "passport_ocr", "passport_review"
    # non-passport branch: skip to done_stage1
    "done_stage1",
]

STAGE_2_STEPS = [
    "gender", "neutered", "birth_date", "breed", "color", "features",
    "photo_avatar",
]

ALL_STEPS = STAGE_1_STEPS + STAGE_2_STEPS

# ── Owner name blacklist ─────────────────────────────────────────────────────

OWNER_NAME_BLACKLIST = {
    "собака", "кошка", "кот", "пёс", "пес", "dog", "cat",
    "самец", "самка", "мальчик", "девочка",
    "да", "нет", "не знаю", "пропустить", "далее", "продолжить",
    "кастрирован", "стерилизована", "стерилизован",
}

# ── Name extraction helpers ──────────────────────────────────────────────────

_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]{1,19}$")

_NAME_STOP_PHRASES = [
    "привет", "здравствуй", "добрый", "доброе", "добрый день",
    "добрый вечер", "доброе утро", "здрасте", "хай", "hello", "hi",
]

_NAME_INTRO_PATTERNS = [
    "его зовут ", "её зовут ", "ее зовут ", "зовут ",
    "кличка ", "имя ", "это ",
    "моего кота зовут ", "мою кошку зовут ", "мою собаку зовут ",
    "моего пса зовут ", "мою собачку зовут ",
]


def _extract_pet_name(text: str) -> str | None:
    """Extract pet name from user text."""
    raw = text.strip()
    msg_lower = raw.lower()

    if msg_lower in _NAME_STOP_PHRASES:
        return None

    cleaned = raw
    for p in _NAME_INTRO_PATTERNS:
        if cleaned.lower().startswith(p):
            cleaned = cleaned[len(p):].strip()
            break

    words = cleaned.split()
    if not words:
        return None

    candidate = words[0].strip(".,!?;:")
    if len(candidate) < 2 or len(candidate) > 20:
        return None
    if not all(c.isalpha() or c == "-" for c in candidate):
        return None

    return candidate[0].upper() + candidate[1:]


# ── Birth date year list ─────────────────────────────────────────────────────

def _get_year_list() -> list[str]:
    """Generate year list for birth_date quick_replies."""
    current_year = datetime.now().year
    return [str(y) for y in range(current_year, current_year - 26, -1)]


# ── get_onboarding_message ───────────────────────────────────────────────────

def get_onboarding_message(step: str, pet_profile: dict) -> dict:
    """Return deterministic message + buttons for the given onboarding step."""

    _name = pet_profile.get("name") or "питомец"
    _species = pet_profile.get("species") or ""
    _gender = pet_profile.get("gender") or ""

    # ── Stage 1 ──

    if step == "pet_count":
        return {
            "text": "Сколько у тебя питомцев?",
            "quick_replies": ["Один", "Двое или больше"],
            "input_type": "buttons",
        }

    if step == "species":
        return {
            "text": "Расскажи, кто у тебя?",
            "quick_replies": ["Собака", "Кот", "Кошка"],
            "input_type": "buttons",
        }

    if step == "name":
        return {
            "text": "Как зовут твоего питомца?",
            "quick_replies": [],
            "input_type": "text",
        }

    if step == "name_reaction_and_gender":
        return {
            "text": f"{_name} — мальчик или девочка?",
            "quick_replies": ["Самец", "Самка"],
            "input_type": "buttons",
        }

    if step == "passport_entry":
        return {
            "text": f"Есть рядом ветеринарный паспорт {_name}? Если сфотографируешь — я сам вытащу породу, дату рождения и прививки.",
            "quick_replies": ["Сфотографировать паспорт", "Заполню позже"],
            "input_type": "buttons",
        }

    if step == "passport_ocr":
        return {
            "text": "Отправь фото паспорта",
            "quick_replies": [],
            "input_type": "photo",
        }

    if step == "passport_review":
        return {
            "text": "Проверь данные из паспорта. Всё верно?",
            "quick_replies": ["Всё верно", "Исправить"],
            "input_type": "buttons",
        }

    if step == "done_stage1":
        return {
            "text": f"Профиль {_name} готов! Хочешь добавить больше информации? Это поможет давать точные советы по питанию и здоровью.",
            "quick_replies": ["Да, давай", "Позже"],
            "input_type": "buttons",
        }

    # ── Stage 2 ──

    if step == "gender":
        if _species == "cat":
            return {
                "text": f"{_name} — кот или кошка?",
                "quick_replies": ["Кот", "Кошка"],
                "input_type": "buttons",
            }
        return {
            "text": f"{_name} — мальчик или девочка?",
            "quick_replies": ["Самец", "Самка"],
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
            "quick_replies": ["Да", "Нет"],
            "input_type": "buttons",
        }

    if step == "birth_date":
        return {
            "text": f"Когда родился {_name}? Если не знаешь точно — выбери год примерно.",
            "quick_replies": _get_year_list()[:10] + ["Не знаю"],
            "input_type": "text",
        }

    if step == "breed":
        return {
            "text": f"Какой породы {_name}?",
            "quick_replies": ["По фото", "Не знаю"],
            "input_type": "text",
        }

    if step == "color":
        return {
            "text": f"Какого окраса {_name}?",
            "quick_replies": ["По фото", "Не знаю"],
            "input_type": "text",
        }

    if step == "features":
        return {
            "text": f"Есть ли у {_name} особые приметы — шрам, пятно, необычный окрас?",
            "quick_replies": ["Пропустить"],
            "input_type": "text",
        }

    if step == "photo_avatar":
        return {
            "text": f"Добавь фото {_name} для карточки. Оно пригодится если питомец потеряется.",
            "quick_replies": ["Загрузить фото", "Пропустить"],
            "input_type": "buttons",
        }

    # Legacy steps (backward compat)
    if step == "name_reaction":
        return {"text": "", "quick_replies": [], "input_type": "none"}

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


# ── validate_onboarding_input ────────────────────────────────────────────────

def validate_onboarding_input(step: str, user_message: str, pet_profile: dict) -> dict:
    """Parse and validate user's answer for the given onboarding step."""

    _msg = user_message.strip()
    _msg_lower = _msg.lower()
    _name = pet_profile.get("name") or "питомец"

    ok = {"valid": True, "parsed_value": None, "field_updates": {}, "error_message": None, "next_step": None}
    fail = {"valid": False, "parsed_value": None, "field_updates": {}, "error_message": None, "next_step": None}

    # ── pet_count ────────────────────────────────────────────────────
    if step == "pet_count":
        if any(k in _msg_lower for k in ("один", "одна", "1")):
            return {**ok, "parsed_value": 1, "field_updates": {"pet_count": 1}}
        if any(k in _msg_lower for k in ("двое", "два", "две", "больше", "много", "несколько", "2", "3", "4", "5")):
            return {**ok, "parsed_value": 2, "field_updates": {"pet_count": 2}}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── species ──────────────────────────────────────────────────────
    if step == "species":
        # Exception #2: cat auto-gender
        if _msg_lower == "кот" or _msg_lower == "котик":
            return {**ok, "parsed_value": "cat", "field_updates": {"species": "cat", "gender": "male"}}
        if _msg_lower == "кошка" or _msg_lower == "кошечка":
            return {**ok, "parsed_value": "cat", "field_updates": {"species": "cat", "gender": "female"}}
        if any(k in _msg_lower for k in ("кот", "кошк", "кис")):
            return {**ok, "parsed_value": "cat", "field_updates": {"species": "cat"}}
        if _msg_lower == "собака" or any(k in _msg_lower for k in ("собак", "пёс", "пес", "щен")):
            return {**ok, "parsed_value": "dog", "field_updates": {"species": "dog"}}
        return {
            **fail,
            "error_message": "Пока я умею помогать только с кошками и собаками. Расскажи, кто у тебя?",
        }

    # ── name ─────────────────────────────────────────────────────────
    if step == "name":
        extracted = _extract_pet_name(_msg)
        if not extracted:
            return {**fail, "error_message": "Хм, не совсем понял. Напиши просто кличку"}
        return {**ok, "parsed_value": extracted, "field_updates": {"name": extracted}}

    # ── name_reaction_and_gender (combined for dogs) ─────────────────
    if step == "name_reaction_and_gender":
        if any(k in _msg_lower for k in ("мальчик", "самец", "кобель")) or _msg_lower == "м":
            return {**ok, "parsed_value": "male", "field_updates": {"gender": "male"}}
        if any(k in _msg_lower for k in ("девочка", "самка", "сука")) or _msg_lower == "ж":
            return {**ok, "parsed_value": "female", "field_updates": {"gender": "female"}}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── name_reaction (legacy, no user input expected) ───────────────
    if step == "name_reaction":
        return ok

    # ── passport_entry ───────────────────────────────────────────────
    if step == "passport_entry":
        if any(k in _msg_lower for k in ("сфотограф", "фото", "да", "есть", "паспорт")):
            return {**ok, "next_step": "passport_ocr"}
        if any(k in _msg_lower for k in ("позже", "нет", "пропуст", "заполню")):
            return {**ok, "next_step": "done_stage1"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── passport_ocr (photo expected from frontend) ──────────────────
    if step == "passport_ocr":
        # Frontend sends OCR result or skip
        return ok

    # ── passport_review ──────────────────────────────────────────────
    if step == "passport_review":
        if any(k in _msg_lower for k in ("верно", "да", "всё", "все", "ок", "правильно")):
            return {**ok, "next_step": "done_stage1"}
        if any(k in _msg_lower for k in ("исправ", "нет", "не так", "ошиб")):
            return {**ok, "next_step": "passport_entry"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── done_stage1 ──────────────────────────────────────────────────
    if step == "done_stage1":
        if any(k in _msg_lower for k in ("да", "давай", "заполн", "сейчас", "конечно")):
            return {**ok, "next_step": "stage2"}
        if any(k in _msg_lower for k in ("позже", "потом", "нет", "пропуст")):
            return {**ok, "next_step": "complete"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── gender ───────────────────────────────────────────────────────
    if step == "gender":
        if any(k in _msg_lower for k in ("кот", "мальчик", "самец", "кобель")) or _msg_lower == "м":
            return {**ok, "parsed_value": "male", "field_updates": {"gender": "male"}}
        if any(k in _msg_lower for k in ("кошка", "девочка", "самка", "сука")) or _msg_lower == "ж":
            return {**ok, "parsed_value": "female", "field_updates": {"gender": "female"}}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── neutered ─────────────────────────────────────────────────────
    if step == "neutered":
        if any(k in _msg_lower for k in ("да", "кастрир", "стерил")):
            return {**ok, "parsed_value": True, "field_updates": {"neutered": True}}
        if _msg_lower == "нет":
            return {**ok, "parsed_value": False, "field_updates": {"neutered": False}}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── birth_date ───────────────────────────────────────────────────
    if step == "birth_date":
        # "Не знаю" → skip
        if any(k in _msg_lower for k in ("не знаю", "не помню", "хз")):
            return {**ok, "parsed_value": None, "field_updates": {"birth_date_skipped": True}}

        # Try full date YYYY-MM-DD
        try:
            parsed_date = datetime.strptime(_msg[:10], "%Y-%m-%d").date()
            today = datetime.now().date()
            min_date = today - timedelta(days=30 * 365)
            if parsed_date <= today and parsed_date >= min_date:
                return {**ok, "parsed_value": str(parsed_date), "field_updates": {"birth_date": str(parsed_date)}}
        except (ValueError, IndexError):
            pass

        # Try just year
        year_match = re.match(r"^(19|20)\d{2}$", _msg.strip())
        if year_match:
            year = int(year_match.group())
            current_year = datetime.now().year
            if current_year - 30 <= year <= current_year:
                approx_date = f"{year}-01-01"
                return {**ok, "parsed_value": approx_date, "field_updates": {"birth_date": approx_date}}

        # Try approx age like "3 года" or "6 месяцев"
        nums = re.findall(r"\d+", _msg)
        if nums:
            val = int(nums[0])
            is_months = "мес" in _msg_lower
            age_years = round(val / 12, 1) if is_months else val
            _species = pet_profile.get("species", "")
            max_age = 25 if _species == "cat" else 20
            if 0 < age_years <= max_age:
                return {**ok, "parsed_value": age_years, "field_updates": {"age_years": age_years}}

        return {**fail, "error_message": "Напиши год рождения, дату или примерный возраст"}

    # ── breed ────────────────────────────────────────────────────────
    if step == "breed":
        if any(k in _msg_lower for k in ("не знаю", "метис", "дворняг", "дворняж")):
            return {**ok, "parsed_value": "метис", "field_updates": {"breed": "метис"}}
        if any(k in _msg_lower for k in ("по фото", "фото")):
            return {**ok, "parsed_value": "photo", "next_step": "breed_photo"}
        if len(_msg.strip()) < 2:
            return {**fail, "error_message": "Напиши породу или нажми 'Не знаю'"}
        return {**ok, "parsed_value": _msg.strip(), "field_updates": {"breed": _msg.strip()}}

    # ── color ────────────────────────────────────────────────────────
    if step == "color":
        if any(k in _msg_lower for k in ("не знаю", "пропуст", "skip")):
            return {**ok, "parsed_value": None, "field_updates": {"color_skipped": True}}
        if any(k in _msg_lower for k in ("по фото", "фото")):
            return {**ok, "parsed_value": "photo", "next_step": "color_photo"}
        if len(_msg.strip()) < 2:
            return {**fail, "error_message": "Опиши окрас или нажми 'Не знаю'"}
        return {**ok, "parsed_value": _msg.strip(), "field_updates": {"color": _msg.strip()}}

    # ── features ─────────────────────────────────────────────────────
    if step == "features":
        if any(k in _msg_lower for k in ("нет", "пропуст", "skip")):
            return {**ok, "parsed_value": None, "field_updates": {"features_skipped": True}}
        return {**ok, "parsed_value": _msg.strip(), "field_updates": {"features": _msg.strip()}}

    # ── photo_avatar ─────────────────────────────────────────────────
    if step == "photo_avatar":
        if any(k in _msg_lower for k in ("загруз", "фото", "да")):
            return {**ok, "parsed_value": "upload", "next_step": "avatar_upload"}
        if any(k in _msg_lower for k in ("пропуст", "нет", "позже", "skip")):
            return {**ok, "parsed_value": None, "field_updates": {}}
        return {**fail, "error_message": "Выбери один из вариантов"}

    # ── Legacy steps (age_choice, age_date, age_approx, optional_gate, chip/stamp) ──

    if step == "age_choice":
        if any(k in _msg_lower for k in ("да", "знаю")):
            return {**ok, "next_step": "age_date"}
        if any(k in _msg_lower for k in ("нет", "примерно")):
            return {**ok, "next_step": "age_approx"}
        return {**fail, "error_message": "Выбери один из вариантов"}

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

    if step == "age_approx":
        nums = re.findall(r"\d+", _msg)
        if not nums:
            return {**fail, "error_message": "Напиши число — сколько лет или месяцев"}
        val = int(nums[0])
        is_months = "мес" in _msg_lower
        age_years = round(val / 12, 1) if is_months else val
        if age_years == 0 and not is_months:
            return {**fail, "error_message": f"Совсем малыш! Сколько {_name} месяцев?"}
        _species = pet_profile.get("species", "")
        max_age = 25 if _species == "cat" else 20
        if age_years > max_age:
            return {**fail, "error_message": f"{_name} правда столько? Напиши ещё раз, чтобы я точно не ошибся"}
        return {**ok, "parsed_value": age_years, "field_updates": {"age_years": age_years}}

    if step == "optional_gate":
        if any(k in _msg_lower for k in ("заполн", "сейчас", "давай", "да")):
            return {**ok, "next_step": "breed"}
        if any(k in _msg_lower for k in ("позже", "потом", "нет", "пропуст")):
            return {**ok, "next_step": "complete"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    if step == "chip_id_ask":
        if _msg_lower in ("да",) or _msg_lower.startswith("да"):
            return {**ok, "next_step": "chip_id_input"}
        if any(k in _msg_lower for k in ("нет", "не знаю")):
            return {**ok, "field_updates": {"chip_id_skipped": True}, "next_step": "stamp_id_ask"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    if step == "chip_id_input":
        digits = re.sub(r"\D", "", _msg)
        if len(digits) == 15:
            return {**ok, "parsed_value": digits, "field_updates": {"chip_id": digits}}
        return {**fail, "error_message": "Номер чипа — это 15 цифр без букв. Проверь и напиши ещё раз"}

    if step == "stamp_id_ask":
        if _msg_lower in ("да",) or _msg_lower.startswith("да"):
            return {**ok, "next_step": "stamp_id_input"}
        if any(k in _msg_lower for k in ("нет", "не знаю")):
            return {**ok, "field_updates": {"stamp_id_skipped": True}, "next_step": "complete"}
        return {**fail, "error_message": "Выбери один из вариантов"}

    if step == "stamp_id_input":
        cleaned = re.sub(r"\s", "", _msg)
        if re.match(r"^[A-Za-zА-Яа-яЁё0-9]{3,8}$", cleaned):
            return {**ok, "parsed_value": cleaned.upper(), "field_updates": {"stamp_id": cleaned.upper()}}
        return {**fail, "error_message": "Обычно клеймо — это несколько букв и цифр. Проверь и напиши ещё раз"}

    # ── unknown step ─────────────────────────────────────────────────
    return ok


# ── get_previous_step ────────────────────────────────────────────────────────

def get_previous_step(current_step: str, pet_profile: dict) -> str | None:
    """Get the previous step for back navigation. Returns None if at first step."""
    # Build the actual step sequence for this user
    steps = list(STAGE_1_STEPS)

    _species = pet_profile.get("species")
    _gender = pet_profile.get("gender")

    # In stage 2
    if current_step in STAGE_2_STEPS:
        steps = list(STAGE_2_STEPS)

    if current_step not in steps:
        return None

    idx = steps.index(current_step)
    if idx == 0:
        return None
    return steps[idx - 1]


# ── is_off_topic ─────────────────────────────────────────────────────────────

# Precompute button sets per step for fast lookup
_BUTTON_MAP: dict[str, set[str]] = {}
for _s in ALL_STEPS + ["optional_gate", "chip_id_ask", "chip_id_input", "stamp_id_ask", "stamp_id_input",
                        "age_choice", "age_date", "age_approx", "name_reaction", "name_reaction_and_gender",
                        "passport_ocr", "passport_review"]:
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

    # Age/birth_date: contains a digit → on-topic
    if step in ("age_approx", "birth_date") and re.search(r"\d", _msg):
        return False

    # Question words + "?" → off-topic question
    if "?" in _msg and any(_msg_lower.startswith(qw) or f" {qw}" in _msg_lower for qw in _QUESTION_WORDS):
        return True

    # Long message with "?" → likely a question
    if len(_msg) > 50 and "?" in _msg:
        return True

    # Fallback: assume on-topic
    return False
