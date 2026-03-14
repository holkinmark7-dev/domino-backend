# routers/onboarding_ai.py
# AI-driven onboarding — backend controls steps, Gemini writes text only.

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

from google import genai
from google.genai import types
from fastapi.responses import JSONResponse
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from rapidfuzz import process as fuzz_process, fuzz
from routers.services.breeds import ALL_BREEDS, BREED_EN
from routers.services.memory import get_user_flags, update_user_flags

logger = logging.getLogger(__name__)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── System prompt ──────────────────────────────────────────────────────────────

_DESIGN_DIR = Path(__file__).parent.parent / "design-reference"

_PROMPT_PATH = _DESIGN_DIR / "onboarding-prompt.txt"
try:
    _PROMPT_TEMPLATE: str = _PROMPT_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    raise RuntimeError(f"[onboarding_ai] Промпт не найден: {_PROMPT_PATH}")

_CHARACTER_PATH = _DESIGN_DIR / "dominik-character.txt"
try:
    _CHARACTER_TEXT: str = _CHARACTER_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    raise RuntimeError(f"[onboarding_ai] Характер не найден: {_CHARACTER_PATH}")

# Fields to collect (for completion check)
_REQUIRED_FIELDS = {"owner_name", "pet_name", "species", "breed", "gender", "is_neutered", "goal"}
_AGE_FIELDS = {"age_years", "birth_date"}

# Empty collected state
_EMPTY_COLLECTED = {
    "owner_name": None,
    "pet_name": None,
    "species": None,
    "breed": None,
    "birth_date": None,
    "age_years": None,
    "gender": None,
    "is_neutered": None,
    "color": None,
    "goal": None,
    "avatar_url": None,
}

# Нейтральные клички — не угадываем пол
_NEUTRAL_NAMES = {
    "бублик", "персик", "соня", "цезарь", "зефир", "карамель",
    "ириска", "солнышко", "лаки", "чарли", "макс", "боня",
    "коржик", "нюша", "симба", "пломбир", "тоша", "кузя",
}

# Явные собачьи клички (минимальный точный список)
_DOG_NAMES = {
    "рекс", "шарик", "бобик", "тузик", "барон", "граф", "буян",
    "полкан", "пират", "дружок", "жучка", "белка", "найда", "пальма",
}

# Явные кошачьи клички (минимальный точный список)
_CAT_NAMES = {
    "мурка", "барсик", "рыжик", "пушок", "васька", "мурзик",
    "китти", "мяу", "снежок", "уголёк", "тигр", "леопард",
}

# Категории пород для уточнения
_BREED_CATEGORIES = {
    "ретривер": "ретривер",
    "лабрадор": "ретривер",
    "голден": "ретривер",
    "золотист": "ретривер",
    "овчарка": "овчарка",
    "немецкая": "овчарка",
    "терьер": "терьер",
    "йорк": "терьер",
    "спаниель": "спаниель",
    "кокер": "спаниель",
    "хаски": "хаски",
    "маламут": "хаски",
    "бульдог": "бульдог",
    "шотландская": "шотландская",
    "вислоухая": "шотландская",
    "такса": "такса",
    "пудель": "пудель",
    "шпиц": "шпиц",
    "пинчер": "пинчер",
}


# ── System prompt builder ────────────────────────────────────────────────────

def _build_system_prompt(collected: dict, step_instruction: str) -> str:
    today = date.today().strftime("%d %B %Y")
    result = _CHARACTER_TEXT + "\n\n" + _PROMPT_TEMPLATE
    result = result.replace("{today_date}", today)
    result = result.replace("{step_instruction}", step_instruction)
    for key in _EMPTY_COLLECTED:
        val = collected.get(key)
        result = result.replace(f"{{{key}}}", str(val) if val is not None else "null")
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_update(existing: dict, new_fields: dict) -> dict:
    """Update collected fields with deduplication protection."""
    merged = dict(existing)
    for key, val in new_fields.items():
        if val is not None and val != "null":
            existing_val = merged.get(key)
            if existing_val and isinstance(val, str) and isinstance(existing_val, str):
                if existing_val in val and val != existing_val:
                    continue
            merged[key] = val
    return merged


def _is_complete(collected: dict) -> bool:
    """Check if all required fields plus at least one age field are filled."""
    required_ok = all(collected.get(f) for f in _REQUIRED_FIELDS)
    age_ok = any(collected.get(f) for f in _AGE_FIELDS)
    return required_ok and age_ok


def _get_fallback_text(step: str, collected: dict) -> str:
    """Return a safe fallback when Gemini returns empty text."""
    pet = collected.get("pet_name", "питомца")
    fallbacks = {
        "owner_name": "Как тебя зовут?",
        "pet_name": "Как зовут питомца?",
        "species": "Кот или собака?",
        "breed": f"Какой породы {pet}?",
        "birth_date": f"Когда родился {pet}?",
        "gender": "Мальчик или девочка?",
        "is_neutered": "Кастрирован?",
        "avatar": f"Добавим фото {pet}?",
        "goal": "Чем могу помочь?",
    }
    return fallbacks.get(step, "Расскажи подробнее.")


# ── Step logic (backend-controlled) ─────────────────────────────────────────

def _get_current_step(collected: dict) -> str:
    """Determine current step based on collected data."""
    if not collected.get("owner_name"):
        return "owner_name"

    if not collected.get("pet_name"):
        return "pet_name"

    # Угадывание вида из клички — СРАЗУ после pet_name
    if not collected.get("species") and not collected.get("_species_guessed"):
        name = (collected.get("pet_name") or "").lower().strip()
        if name in _DOG_NAMES:
            return "species_guess_dog"
        elif name in _CAT_NAMES:
            return "species_guess_cat"

    if not collected.get("goal"):
        return "goal"

    # Если была тревога — дать высказаться
    if collected.get("goal") == "Есть тревога" and not collected.get("_concern_heard"):
        return "concern"

    if not collected.get("species"):
        return "species"

    # Паспорт — только если не пропущен и нет breed
    if not collected.get("breed") and not collected.get("_passport_skipped"):
        return "passport_offer"

    # Порода
    if not collected.get("breed"):
        if collected.get("_breed_category"):
            return "breed_subcategory"
        return "breed"

    # Дата/возраст
    if not collected.get("birth_date") and not collected.get("age_years") and not collected.get("_age_skipped"):
        return "birth_date"

    # Пол — пропускаем если уже определён (кот/кошка)
    if not collected.get("gender"):
        return "gender"

    if collected.get("is_neutered") is None and not collected.get("_neutered_skipped"):
        return "is_neutered"

    if not collected.get("avatar_url") and not collected.get("_avatar_skipped"):
        return "avatar"

    return "complete"


def _get_step_instruction(step: str, collected: dict) -> str:
    """Return Gemini instruction for a specific step."""
    owner = collected.get("owner_name") or "хозяин"
    pet_name = collected.get("pet_name") or "питомец"
    species = collected.get("species") or ""
    gender = collected.get("gender") or ""

    # Определяем форму слова для кастрации
    if species == "cat" and gender == "female":
        neutered_word = "стерилизована"
    elif species == "dog" and gender == "female":
        neutered_word = "стерилизована"
    else:
        neutered_word = "кастрирован"

    instructions = {
        "owner_name": (
            'Поприветствуй тепло и коротко. Скажи что ты Dominik и рад что человек здесь. '
            'Спроси как зовут. Никакой ветеринарии, никаких объяснений что ты умеешь. '
            'Пример точного текста: "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?"'
        ),

        "pet_name": (
            f'Скажи "{owner}" приятно познакомиться и сразу спроси кличку питомца. '
            f'Одно предложение. Без лишних слов. '
            f'Пример: "Приятно, {owner}. Как зовут твоего питомца?"'
        ),

        "species_guess_dog": (
            f'Кличка {pet_name} — угадай что это собака. Скажи уверенно, коротко. '
            f'Не спрашивай "кто это такой". Ты угадываешь — проверяешь угадал ли. '
            f'Точный пример: "Ставлю на собаку — угадал?"'
        ),

        "species_guess_cat": (
            f'Кличка {pet_name} — угадай что это кошка. Скажи уверенно, коротко. '
            f'Не спрашивай "кто это такой". Ты угадываешь — проверяешь угадал ли. '
            f'Точный пример: "Ставлю на кота — угадал?"'
        ),

        "goal": (
            f'Скажи что {pet_name} повезло — у него есть хозяин. Используй кличку в дательном падеже. '
            f'Сразу спроси чем можешь помочь. Максимум два коротких предложения. '
            f'Пример: "Бобику повезло — у него есть ты. Чем могу помочь?"'
        ),

        "concern": (
            f'Пользователь беспокоится. Спроси что происходит с {pet_name} — используй кличку в творительном падеже. '
            f'Коротко. Дай высказаться полностью. '
            f'Пример: "Расскажи. Что происходит с Бобиком?"'
        ),

        "species": (
            f'Пользователь написал про другое животное. Скажи тепло что пока работаешь только с кошками и собаками. '
            f'Спроси — кошка или собака? Одно-два предложения. '
            f'Пример: "Пока работаю только с кошками и собаками. Кошка или собака есть?"'
            if collected.get("_exotic_attempt") else
            'Спроси кошка или собака. Одно короткое предложение. '
            'Пример: "Кошка или собака?"'
        ),

        "passport_offer": (
            'Предложи сфотографировать ветпаспорт. Скажи что сам перенесёшь данные в карточку. '
            'Коротко, по-деловому. '
            'Пример: "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу в карточку."'
        ),

        "breed": (
            'Пользователь сказал что знает породу. Попроси написать название. '
            'Одно предложение. Не повторяй вопрос о породе. '
            'Пример: "Напиши название — внесу в карточку."'
            if collected.get("_awaiting_breed_text") else

            f'Пользователь не знает породу {pet_name}. '
            'Предложи сфотографировать — ты определишь по фото. '
            'Или можно выбрать "Метис". Одно-два предложения. '
            'Пример: "Сфотографируй — определю породу по фото. Или выбери Метис."'
            if collected.get("_breed_unknown") else

            f'Спроси название породы {pet_name} — используй кличку в родительном падеже. '
            f'Если метис — тоже хорошо, пусть скажет. '
            f'Одно короткое предложение без вариантов. '
            f'Пример для собаки: "Какая порода у Бобика? Если метис — тоже скажи." '
            f'Пример для кошки: "Какая порода у Мурки? Если беспородная — тоже скажи."'
        ),

        "breed_subcategory": (
            f'Уточни подпороду. Скажи что бывают разные варианты. '
            f'Одно предложение. '
            f'Примеры: '
            f'"Ретриверы бывают разные — уточни:" '
            f'"Овчарки бывают разные — уточни:" '
            f'"Лабрадоры бывают разные — золотистый или обычный? Уточни:"'
        ),

        "breed_insight": (
            f'Дай живой инсайт про породу {collected.get("breed", "питомца")}. '
            f'Одно-два предложения про характер или главную особенность породы. '
            f'Никаких медицинских предупреждений. Живо, как друг который знает эту породу. '
            f'После инсайта — не задавай вопросов. Следующий вопрос придёт отдельно. '
            f'Примеры стиля: '
            f'"Лабрадоры едят за троих и искренне не понимают зачем им ограничивают порцию." '
            f'"Золотистые — вечные щенки душой. Суставы у них слабое место с возрастом." '
            f'"Немецкие овчарки умны до неудобства — если скучно, найдут себе занятие."'
        ),

        "birth_date": (
            f'Скажи что дата рождения нужна чтобы считать прививки и осмотры точно. '
            f'Спроси когда родился {pet_name} — используй кличку в родительном падеже. '
            f'Скажи что если не знает точную дату — можно указать примерный возраст или пропустить. '
            f'Максимум два-три коротких предложения. '
            f'Пример: "Дата нужна — чтобы считать прививки точно, не примерно. '
            f'Когда родился Бобик? Если не знаешь точно — скажи примерный возраст."'
        ),

        "gender": (
            f'Спроси пол {pet_name} — используй кличку в родительном падеже. '
            f'Если кличка явно мужская — подтверди "мальчик?". '
            f'Если явно женская — подтверди "девочка?". '
            f'Если непонятно — спроси прямо. '
            f'Примеры: '
            f'"Бобик — мальчик?" (мужская кличка) '
            f'"Мурка — девочка?" (женская кличка) '
            f'"Кнопка — мальчик или девочка?" (нейтральная кличка)'
        ),

        "is_neutered": (
            f'Спроси {neutered_word} ли {pet_name} — используй кличку в родительном падеже. '
            f'Одно короткое предложение. '
            f'Примеры: '
            f'"Бобик кастрирован?" (кот или пёс) '
            f'"Мурка стерилизована?" (кошка или сука)'
        ),

        "avatar": (
            f'Скажи что это последний штрих — фото для профиля {pet_name}. '
            f'Используй кличку в родительном падеже. '
            f'Коротко и тепло. '
            f'Пример: "Последний штрих — фото для профиля Бобика. Можно сфотографировать сейчас или пропустить."'
        ),
    }

    # Эти фразы запрещены в любом ответе Gemini:
    # "Понял", "Отлично", "Прекрасно", "Замечательно", "Конечно", "Разумеется",
    # "Зафиксировал", "Приятно познакомиться", "Рад помочь", "С чего начнём"
    # Никаких emoji. Максимум 2-3 предложения на шаг.

    return instructions.get(step, "Продолжи разговор естественно.")


def _get_gender_quick_replies(pet_name: str) -> list:
    """Determine gender buttons based on pet name heuristic."""
    name_lower = (pet_name or "").lower()

    if name_lower in _NEUTRAL_NAMES:
        return [
            {"label": "Мальчик", "value": "Мальчик", "preferred": False},
            {"label": "Девочка", "value": "Девочка", "preferred": False},
        ]

    if name_lower in _DOG_NAMES or name_lower in _CAT_NAMES:
        # Известная кличка — предлагаем с preferred
        is_male = name_lower in _DOG_NAMES
        if is_male:
            return [
                {"label": "Да, мальчик", "value": "Да, мальчик", "preferred": True},
                {"label": "Нет, девочка", "value": "Нет, девочка", "preferred": False},
            ]
        else:
            return [
                {"label": "Да, девочка", "value": "Да, девочка", "preferred": True},
                {"label": "Нет, мальчик", "value": "Нет, мальчик", "preferred": False},
            ]
    else:
        return [
            {"label": "Мальчик", "value": "Мальчик", "preferred": False},
            {"label": "Девочка", "value": "Девочка", "preferred": False},
        ]


def _get_breed_subcategory_buttons(category: str) -> list:
    """Кнопки уточнения категории породы."""
    subcategories = {
        "ретривер": ["Золотистый ретривер", "Лабрадор-ретривер", "Плоскошёрстный ретривер", "Другая"],
        "овчарка": ["Немецкая овчарка", "Бельгийская малинуа", "Австралийская овчарка", "Бордер-колли", "Другая"],
        "терьер": ["Йоркширский терьер", "Джек-рассел", "Бультерьер", "Другая"],
        "спаниель": ["Кокер-спаниель", "Спрингер-спаниель", "Кавалер кинг чарльз", "Другая"],
        "хаски": ["Сибирский хаски", "Аляскинский маламут", "Другая"],
        "бульдог": ["Английский бульдог", "Французский бульдог", "Американский бульдог", "Другая"],
        "шотландская": ["Шотландская вислоухая", "Шотландская прямоухая", "Другая"],
        "такса": ["Стандартная такса", "Миниатюрная такса", "Кроличья такса", "Другая"],
        "пудель": ["Той-пудель", "Миниатюрный пудель", "Стандартный пудель", "Другая"],
        "шпиц": ["Померанский шпиц", "Немецкий шпиц", "Японский шпиц", "Другая"],
        "пинчер": ["Доберман", "Цвергпинчер", "Другая"],
    }
    breeds = subcategories.get(category.lower(), [])
    return [
        {"label": b, "value": b if b != "Другая" else "Другая порода", "preferred": False}
        for b in breeds
    ]


def _get_step_quick_replies(step: str, collected: dict) -> list:
    """Return quick reply buttons for a specific step. Backend-controlled, not Gemini."""
    pet = collected.get("pet_name") or ""

    qr_map = {
        "owner_name": [],

        "pet_name": [],

        "species_guess_dog": [
            {"label": "Да, пёс", "value": "Да, пёс", "preferred": True},
            {"label": "Не угадал", "value": "Не угадал", "preferred": False},
        ],

        "species_guess_cat": [
            {"label": "Кот", "value": "Кот", "preferred": True},
            {"label": "Кошка", "value": "Кошка", "preferred": False},
            {"label": "Не угадал", "value": "Не угадал", "preferred": False},
        ],

        "goal": [
            {"label": "Слежу за здоровьем", "value": "Слежу за здоровьем", "preferred": False},
            {"label": "Прививки и плановое", "value": "Прививки и плановое", "preferred": False},
            {"label": "Веду дневник", "value": "Веду дневник", "preferred": False},
            {"label": "Кое-что беспокоит", "value": "Кое-что беспокоит", "preferred": False},
        ],

        "concern": [],

        "species": [
            {"label": "Кот", "value": "Кот", "preferred": False},
            {"label": "Кошка", "value": "Кошка", "preferred": False},
            {"label": "Собака", "value": "Собака", "preferred": False},
        ],

        "passport_offer": [
            {"label": "Сфотографирую", "value": "Сфотографирую", "preferred": True},
            {"label": "Заполню сам", "value": "Заполню сам", "preferred": False},
            {"label": "Паспорта нет", "value": "Паспорта нет", "preferred": False},
        ],

        "breed": (
            []
            if collected.get("_awaiting_breed_text")
            else [
                {"label": "Сфотографировать", "value": "BREED_PHOTO", "preferred": True},
                {"label": "Метис / Не знаю", "value": "Не знаю породу", "preferred": False},
            ]
            if collected.get("_breed_unknown")
            else [
                {"label": "Знаю породу", "value": "Знаю породу", "preferred": True},
                {"label": "Не знаю породу", "value": "Не знаю породу", "preferred": False},
            ]
        ),

        "breed_subcategory": [],

        "birth_date": [
            {"label": "Знаю дату", "value": "Знаю дату", "preferred": True},
            {"label": "Примерный возраст", "value": "Примерный возраст", "preferred": False},
            {"label": "Не знаю", "value": "Не знаю возраст", "preferred": False},
        ],

        "gender": _get_gender_quick_replies(pet),

        "is_neutered": [
            {"label": "Да", "value": "Да", "preferred": False},
            {"label": "Нет", "value": "Нет", "preferred": False},
        ],

        "avatar": [
            {"label": "Сфотографировать", "value": "AVATAR_PHOTO", "preferred": True},
            {"label": "Пропустить", "value": "Пропустить", "preferred": False},
        ],
    }

    # Динамические кнопки для подкатегорий пород
    if step == "breed_subcategory":
        category = collected.get("_breed_category", "")
        if category == "other":
            return [{"label": "Метис / Не знаю", "value": "Не знаю породу", "preferred": False}]
        return _get_breed_subcategory_buttons(category)

    return qr_map.get(step, [])


# ── User input parser (no Gemini) ───────────────────────────────────────────

def _parse_age(msg: str) -> dict | None:
    """Parse age from message using regex. Returns dict with birth_date or age_years, or None."""
    # DD.MM.YYYY or DD/MM/YYYY
    match = re.search(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', msg)
    if match:
        d, m, y = match.groups()
        return {"birth_date": f"{y}-{m.zfill(2)}-{d.zfill(2)}"}
    # YYYY-MM-DD (ISO format from date picker)
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', msg)
    if match:
        return {"birth_date": match.group(0)}
    # X лет / X месяцев
    age_match = re.search(r'(\d+)\s*(лет|год|года|месяц|месяца|месяцев)', msg.lower())
    if age_match:
        num = float(age_match.group(1))
        unit = age_match.group(2)
        if "месяц" in unit:
            return {"age_years": round(num / 12, 1)}
        return {"age_years": num}
    return None


def _parse_age_with_gemini(msg: str, client) -> dict | None:
    """Fallback: ask Gemini to extract age from free-text message."""
    if not client:
        return None
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "Из сообщения пользователя извлеки дату рождения или возраст питомца.\n"
                "Верни ТОЛЬКО JSON без markdown:\n"
                '{"birth_date":"YYYY-MM-DD"} или {"age_years":число} или {"unknown":true}\n'
                f"Сообщение: {msg}"
            ),
        )
        import json as _json
        raw = (resp.text or "").strip().strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        data = _json.loads(raw)
        if data.get("birth_date"):
            return {"birth_date": data["birth_date"]}
        if data.get("age_years") is not None:
            return {"age_years": float(data["age_years"])}
    except Exception as e:
        logger.warning("[_parse_age_with_gemini] %s", e)
    return None


def _parse_name(msg: str) -> str | None:
    """Extract a name from message using regex. Handles 'Меня зовут X', 'Я X', etc."""
    msg = msg.strip()
    # "Меня зовут Марк" / "Зовут Марк"
    m = re.search(r'(?:меня\s+)?зовут\s+(\S+)', msg, re.IGNORECASE)
    if m:
        return m.group(1).strip(".,!?")
    # "Я Марк" / "Я — Марк"
    m = re.search(r'^я\s*[—–-]?\s*(\S+)', msg, re.IGNORECASE)
    if m:
        return m.group(1).strip(".,!?")
    # "Это Марк" / "Его зовут Рекс" / "Её зовут Мурка"
    m = re.search(r'(?:это|его|её|ее)\s+(?:зовут\s+)?(\S+)', msg, re.IGNORECASE)
    if m:
        return m.group(1).strip(".,!?")
    # Single word — just the name itself
    words = msg.split()
    if len(words) == 1:
        return words[0].strip(".,!?")
    # First capitalized word (not first word which might be "ну", "а")
    for w in words:
        clean = w.strip(".,!?")
        if clean and clean[0].isupper():
            return clean
    return None


def _parse_name_with_gemini(msg: str, field: str, client) -> str | None:
    """Fallback: ask Gemini to extract a name from free-text message."""
    if not client:
        return None
    label = "имя хозяина" if field == "owner_name" else "кличку питомца"
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                f"Из сообщения пользователя извлеки {label}.\n"
                "Верни ТОЛЬКО имя одним словом, без кавычек и пояснений.\n"
                f"Сообщение: {msg}"
            ),
        )
        name = (resp.text or "").strip().strip('"\'.,!?')
        if name and len(name) < 30:
            return name
    except Exception as e:
        logger.warning("[_parse_name_with_gemini] %s", e)
    return None


def _parse_user_input(message: str, step: str, collected: dict, client=None) -> dict:
    """Extract data from user message. Uses Gemini as fallback for complex inputs."""
    msg = message.strip()
    msg_lower = msg.lower()
    updates = {}

    if step == "owner_name":
        name = _parse_name(msg) or _parse_name_with_gemini(msg, "owner_name", client) or msg
        updates["owner_name"] = name

    elif step == "pet_name":
        name = _parse_name(msg) or _parse_name_with_gemini(msg, "pet_name", client) or msg
        updates["pet_name"] = name

    elif step == "species_guess_dog":
        if any(w in msg_lower for w in ["да", "пёс", "пес", "собака"]):
            updates["species"] = "dog"
            updates["_species_guessed"] = True
        else:
            # "Не угадал" → переходим к goal без species
            updates["_species_guessed"] = True

    elif step == "species_guess_cat":
        if "кот" in msg_lower and "кошка" not in msg_lower:
            updates["species"] = "cat"
            updates["gender"] = "male"
            updates["_species_guessed"] = True
        elif "кошка" in msg_lower:
            updates["species"] = "cat"
            updates["gender"] = "female"
            updates["_species_guessed"] = True
        else:
            updates["_species_guessed"] = True

    elif step == "goal":
        goal_map = {
            "слежу за здоровьем": "Слежу за здоровьем",
            "прививки и плановое": "Прививки и плановое",
            "веду дневник": "Веду дневник",
            "кое-что беспокоит": "Есть тревога",
        }
        for key, val in goal_map.items():
            if key in msg_lower:
                updates["goal"] = val
                break
        if not updates.get("goal"):
            updates["goal"] = msg

    elif step == "concern":
        # Пользователь рассказал о проблеме
        updates["_concern_heard"] = True

    elif step == "species":
        _EXOTIC_ANIMALS = {
            "хомяк", "хомячок", "попугай", "попугайчик", "рыбка", "рыба",
            "черепаха", "черепашка", "хорёк", "хорек", "кролик", "крыса",
            "морская свинка", "шиншилла", "ящерица", "змея", "игуана",
            "птица", "птичка", "канарейка", "волнистый", "hamster", "parrot",
            "rabbit", "turtle", "ferret", "fish", "guinea pig",
        }
        if "кот" in msg_lower and "кошка" not in msg_lower:
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif "кошка" in msg_lower:
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif any(w in msg_lower for w in ["собака", "пёс", "пес"]):
            updates["species"] = "dog"
        elif any(w in msg_lower for w in _EXOTIC_ANIMALS):
            updates["_exotic_attempt"] = True

    elif step == "passport_offer":
        if any(w in msg_lower for w in ["заполню", "сам", "нет", "паспорта нет", "вручную"]):
            updates["_passport_skipped"] = True

    elif step == "breed":
        if msg_lower == "знаю породу":
            updates["_awaiting_breed_text"] = True

        elif msg_lower in ["не знаю породу", "метис / не знаю", "не знаю"]:
            if collected.get("_breed_unknown"):
                # Второй раз "не знаю" — записываем Метис
                updates["breed"] = "Метис"
            else:
                # Первый раз — показать кнопки фото
                updates["_breed_unknown"] = True

        elif msg == "BREED_PHOTO":
            pass  # Фронт открывает камеру

        elif "метис" in msg_lower or "дворняга" in msg_lower or "беспородн" in msg_lower:
            updates["breed"] = "Метис"

        else:
            # Пользователь написал название породы
            # 1. Проверяем категории
            category = None
            for key, cat in _BREED_CATEGORIES.items():
                if key in msg_lower:
                    category = cat
                    break

            if category:
                updates["_breed_category"] = category
                updates["_awaiting_breed_text"] = None
            else:
                # 2. Rapidfuzz по 309 породам
                match = fuzz_process.extractOne(msg, ALL_BREEDS, scorer=fuzz.WRatio, score_cutoff=80)
                if match:
                    updates["breed"] = match[0]
                elif collected.get("_awaiting_breed_text"):
                    # Пользователь написал после "Знаю породу" — записываем как есть
                    updates["breed"] = msg.strip()
                else:
                    updates["breed"] = msg.strip()
                updates["_breed_category"] = None
                updates["_awaiting_breed_text"] = None

    elif step == "breed_subcategory":
        if "другая" in msg_lower:
            updates["_breed_category"] = "other"
            # Ждём ввода текстом
        else:
            updates["breed"] = msg
            updates["_breed_category"] = None

    elif step == "birth_date":
        if msg_lower in ["знаю дату", "введу дату"]:
            updates["_wants_date_picker"] = True
        elif msg_lower in ["не знаю", "не знаю возраст", "незнаю", "пропустить"]:
            updates["_age_skipped"] = True
        elif msg_lower in ["примерный возраст", "полных лет", "примерный", "примерно"]:
            updates["_age_approximate"] = True
        else:
            parsed = _parse_age(msg) or _parse_age_with_gemini(msg, client)
            if parsed:
                updates.update(parsed)
                updates["_wants_date_picker"] = None
                updates["_age_approximate"] = None

    elif step == "gender":
        if any(w in msg_lower for w in ["мальчик", "самец", "пёс", "кобель"]):
            updates["gender"] = "male"
        elif any(w in msg_lower for w in ["девочка", "самка", "сука"]):
            updates["gender"] = "female"
        elif msg_lower.strip().rstrip(".,!") == "да":
            # "Да" без контекста — определяем по кличке
            pet_name_lower = collected.get("pet_name", "").lower()
            if pet_name_lower in _CAT_NAMES:
                updates["gender"] = "female"
            else:
                updates["gender"] = "male"
        # Если ничего не совпало — шаг повторяется

    elif step == "is_neutered":
        msg_clean = msg.strip().rstrip(".,!?;:").lower()
        if msg_clean in {"да", "yes", "кастрирован", "стерилизована"}:
            updates["is_neutered"] = True
        elif msg_clean in {"нет", "no", "не кастрирован", "не стерилизована"}:
            updates["is_neutered"] = False

    elif step == "avatar":
        if "пропуст" in msg_lower:
            updates["_avatar_skipped"] = True

    return updates


# ── Pet creation ─────────────────────────────────────────────────────────────

def _create_pet(user_id: str, collected: dict) -> str | None:
    """Create pet in supabase from collected data. Returns pet_id or None."""
    try:
        species_raw = (collected.get("species") or "").lower()
        if "cat" in species_raw or "кош" in species_raw or "кот" in species_raw:
            species = "cat"
        else:
            species = "dog"

        gender_raw = (collected.get("gender") or "").lower()
        if any(w in gender_raw for w in ["female", "девочк", "самка", "женск"]):
            gender = "female"
        elif any(w in gender_raw for w in ["male", "мальчик", "самец", "мужск"]):
            gender = "male"
        else:
            gender = None

        neutered_raw = str(collected.get("is_neutered") or "").lower()
        is_neutered = neutered_raw in {"да", "yes", "true", "1", "кастрирован", "стерилизован", "стерилизована"}

        birth_date = collected.get("birth_date")
        if birth_date:
            m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", str(birth_date))
            if m:
                birth_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

        age_raw = collected.get("age_years")
        try:
            age_years = float(age_raw) if age_raw is not None else None
        except (ValueError, TypeError):
            age_years = None

        row = {
            "user_id": user_id,
            "name": collected.get("pet_name") or "Питомец",
            "species": species,
            "breed": collected.get("breed"),
            "gender": gender,
            "neutered": is_neutered,
            "birth_date": birth_date,
            "age_years": age_years,
            "color": collected.get("color"),
            "avatar_url": collected.get("avatar_url"),
        }
    except Exception as e:
        logger.error("[create_pet] build row failed: %s", e)
        return None

    # Block 1 — create pet
    try:
        result = supabase.table("pets").insert(row).execute()
        pet_id = result.data[0]["id"]
    except Exception as e:
        logger.error("[create_pet] INSERT pets failed: %s", e)
        return None

    # Block 2 — update user (independent, pet_id already exists)
    try:
        current = supabase.table("users").select("pet_count").eq("id", user_id).single().execute()
        count = (current.data.get("pet_count") or 0) + 1
        supabase.table("users").update({
            "is_onboarded": True,
            "owner_name": collected.get("owner_name"),
            "pet_count": count,
        }).eq("id", user_id).execute()
    except Exception as e:
        logger.error("[create_pet] UPDATE users failed: %s", e)

    # Block 3 — link onboarding chat history to new pet
    try:
        supabase.table("chat").update({"pet_id": pet_id}).eq("user_id", user_id).is_("pet_id", "null").execute()
    except Exception as e:
        logger.error("[create_pet] UPDATE chat failed: %s", e)

    return pet_id


# ── Chat persistence ────────────────────────────────────────────────────────

def _load_chat_history(user_id: str, limit: int = 20) -> list[dict]:
    """Load recent onboarding chat messages (no pet_id) for this user."""
    try:
        result = (
            supabase.table("chat")
            .select("role, message")
            .eq("user_id", user_id)
            .is_("pet_id", "null")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error("[load_chat_history] %s", e)
        return []


def _save_ai_message(user_id: str, text: str, pet_id: str | None, user_chat_id: str | None) -> None:
    try:
        supabase.table("chat").insert({
            "user_id": user_id,
            "pet_id": pet_id,
            "message": text,
            "role": "ai",
            "linked_chat_id": user_chat_id,
            "mode": "ONBOARDING",
        }).execute()
    except Exception as e:
        logger.error("[save_ai_message] %s", e)


def _save_user_message(user_id: str, text: str) -> str | None:
    """Save user message, return its id."""
    try:
        result = supabase.table("chat").insert({
            "user_id": user_id,
            "pet_id": None,
            "message": text,
            "role": "user",
            "mode": "user",
        }).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        logger.error("[save_user_message] %s", e)
    return None


# ── Pet card & completion text ───────────────────────────────────────────────

def _build_pet_card(collected: dict, pet_id: str) -> dict:
    """Build pet card dict for UI response."""
    species_raw = (collected.get("species") or "").lower()
    species_display = "Кошка" if "cat" in species_raw or "кош" in species_raw or "кот" in species_raw else "Собака"

    gender_raw = (collected.get("gender") or "").lower()
    if any(w in gender_raw for w in ["female", "девочк", "самка"]):
        gender_display = "Самка"
    elif any(w in gender_raw for w in ["male", "мальчик", "самец"]):
        gender_display = "Самец"
    else:
        gender_display = collected.get("gender") or "—"

    neutered_raw = str(collected.get("is_neutered") or "").lower()
    neutered_display = "Да" if neutered_raw in {"да", "yes", "true", "1", "кастрирован", "стерилизован", "стерилизована"} else "Нет"

    age_display = "—"
    if collected.get("birth_date"):
        try:
            bd_str = str(collected["birth_date"])
            m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", bd_str)
            if m:
                bd_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            bd = date.fromisoformat(bd_str)
            years = (date.today() - bd).days / 365.25
            if years < 1:
                months = int(years * 12)
                age_display = f"{months} мес."
            else:
                age_display = f"{int(years)} лет"
        except Exception:
            pass
    elif collected.get("age_years") is not None:
        age_display = f"{collected['age_years']} лет"

    return {
        "id": pet_id,
        "name": collected.get("pet_name") or "Питомец",
        "species": species_display,
        "breed": collected.get("breed") or "—",
        "breed_en": BREED_EN.get(collected.get("breed") or "", collected.get("breed") or "—"),
        "gender": gender_display,
        "age": age_display,
        "neutered": neutered_display,
        "avatar_url": collected.get("avatar_url"),
    }


def _build_completion_text(collected: dict) -> str:
    """Generate completion text based on goal. No Gemini needed."""
    goal = collected.get("goal", "")
    pet = collected.get("pet_name") or "питомец"

    texts = {
        "Есть тревога":
            f"Карточка готова. Профиль {pet} уже заполнен — но сначала расскажи, что тебя беспокоит?",
        "Слежу за здоровьем":
            f"Всё на месте. Открой профиль {pet} — там уже всё что ты рассказал. Дополнить можно в любой момент.",
        "Прививки и плановое":
            f"Готово. Профиль {pet} создан — загляни туда, там уже основное. Остальное внесём вместе.",
        "Веду дневник":
            f"Карточка {pet} готова. Открой профиль и дополни что знаешь, или просто пиши мне.",
    }
    return texts.get(goal, f"Карточка {pet} готова. Открой профиль — там уже всё основное.")


# ── Main handler ─────────────────────────────────────────────────────────────

def handle_onboarding_ai(
    user_id: str,
    message_text: str,
    passport_ocr_data: dict | None = None,
    breed_detection_data: dict | None = None,
) -> JSONResponse:
    """
    Handle one turn of AI-driven onboarding.
    Backend controls steps & quick_replies. Gemini writes text only.
    """
    # 1. Load accumulated collected data from user flags
    user_flags = get_user_flags(user_id)
    collected: dict = dict(_EMPTY_COLLECTED)
    collected.update(user_flags.get("onboarding_collected") or {})

    # 2. Handle special inputs (OCR, breed detection, avatar)
    actual_message = message_text
    override_quick_replies = None

    # 2a. Passport OCR
    if passport_ocr_data and passport_ocr_data.get("success") and passport_ocr_data.get("confidence", 0) >= 0.6:
        ocr_fields = {"pet_name", "breed", "birth_date", "gender", "is_neutered"}
        ocr_updates = {f: passport_ocr_data[f] for f in ocr_fields if passport_ocr_data.get(f) and not collected.get(f)}
        collected = _safe_update(collected, ocr_updates)
        collected["_passport_skipped"] = True
        actual_message = "Паспорт отсканирован, данные заполнены автоматически."
    elif passport_ocr_data:
        collected["_passport_skipped"] = True
        actual_message = "Не удалось прочитать паспорт. Заполним вручную."

    # 2b. Breed detection
    elif breed_detection_data and breed_detection_data.get("success"):
        breeds = breed_detection_data.get("breeds", [])
        color = breed_detection_data.get("color")

        if breeds:
            top = breeds[0]
            if top["probability"] > 0.7:
                # Высокая уверенность — записываем автоматически
                collected["breed"] = top["name_ru"]
                if color:
                    collected["color"] = color
                actual_message = (
                    f"По фото определил породу: {top['name_ru']} "
                    f"({int(top['probability'] * 100)}% уверенность). "
                    f"Окрас: {color or 'не определён'}."
                )
            else:
                # Несколько вариантов — показываем пользователю, early return
                ai_text = "Вижу несколько вариантов по фото."
                breed_qr = [
                    {
                        "label": f"{b['name_ru']} ({int(b['probability'] * 100)}%)",
                        "value": b["name_ru"],
                        "preferred": i == 0,
                    }
                    for i, b in enumerate(breeds[:3])
                ]
                breed_qr.append({"label": "Другая порода", "value": "Другая порода", "preferred": False})

                # Save state before early return
                user_chat_id = _save_user_message(user_id, "Фото для определения породы")
                user_flags["onboarding_collected"] = collected
                update_user_flags(user_id, user_flags)
                _save_ai_message(user_id, ai_text, None, user_chat_id)

                return JSONResponse(content={
                    "ai_response": ai_text,
                    "quick_replies": breed_qr,
                    "onboarding_phase": "collecting",
                    "pet_id": None,
                    "pet_card": None,
                    "input_type": "text",
                    "collected": collected,
                })
        else:
            actual_message = "Не удалось определить породу по фото."

    # 2c. Avatar URL from message text
    elif message_text and message_text.startswith("avatar_url:"):
        avatar_url = message_text[len("avatar_url:"):]
        if avatar_url:
            collected["avatar_url"] = avatar_url
        actual_message = "Фото загружено."

    # 3. Parse user input (text messages only, not special inputs)
    current_step = _get_current_step(collected)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    if actual_message and actual_message == message_text:
        updates = _parse_user_input(actual_message, current_step, collected, client=client)
        collected.update(updates)
        current_step = _get_current_step(collected)

    # 4. Save user message
    user_chat_id = None
    if actual_message and actual_message.strip():
        user_chat_id = _save_user_message(user_id, actual_message)

    # 5. Save collected to flags (before any early return)
    user_flags["onboarding_collected"] = collected
    update_user_flags(user_id, user_flags)

    # 6. Check completion — early return without Gemini
    if current_step == "complete" or _is_complete(collected):
        pet_id = _create_pet(user_id, collected)
        if pet_id:
            user_flags["onboarding_collected"] = None
            user_flags["onboarding_pet_id"] = pet_id
            update_user_flags(user_id, user_flags)

            pet_card = _build_pet_card(collected, pet_id)
            ai_text = _build_completion_text(collected)
            _save_ai_message(user_id, ai_text, pet_id, user_chat_id)

            return JSONResponse(content={
                "ai_response": ai_text,
                "quick_replies": [],
                "onboarding_phase": "complete",
                "pet_id": pet_id,
                "pet_card": pet_card,
                "input_type": "text",
                "collected": collected,
            })

    # 7. Get step instruction and quick replies
    step_instruction = _get_step_instruction(current_step, collected)
    quick_replies = override_quick_replies or _get_step_quick_replies(current_step, collected)

    # 8. Call Gemini — text only, no JSON
    try:
        history_rows = _load_chat_history(user_id, limit=20)
        gemini_history = []
        for row in history_rows:
            role = "model" if row["role"] == "ai" else "user"
            content = row.get("message") or ""
            if content:
                gemini_history.append({"role": role, "parts": [{"text": content}]})

        system_prompt = _build_system_prompt(collected, step_instruction)

        chat = client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
            history=gemini_history,
        )
        response = chat.send_message(actual_message or "Начни онбординг")
        ai_text = (response.text or "").strip()
    except Exception as e:
        logger.error("[gemini_call] %s", e)
        ai_text = "Что-то пошло не так. Попробуй ещё раз."

    if not ai_text:
        ai_text = _get_fallback_text(current_step, collected)

    # 9. Save AI response
    _save_ai_message(user_id, ai_text, None, user_chat_id)

    # 10. Return response
    return JSONResponse(content={
        "ai_response": ai_text,
        "quick_replies": quick_replies,
        "onboarding_phase": "collecting",
        "pet_id": None,
        "pet_card": None,
        "input_type": "date_picker" if collected.get("_wants_date_picker") else "text",
        "collected": collected,
    })
