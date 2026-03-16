# routers/onboarding_ai.py
# AI-driven onboarding v2.0 — backend controls steps, Gemini writes text only.

import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

import openai
from google import genai
from google.genai import types
from fastapi.responses import JSONResponse
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from rapidfuzz import fuzz
from routers.services.breeds import ALL_BREEDS, BREED_EN
from routers.services.memory import get_user_flags, update_user_flags

logger = logging.getLogger(__name__)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── System prompt files ────────────────────────────────────────────────────────

_DESIGN_DIR = Path(__file__).parent.parent / "design-reference"

_CHARACTER_PATH = _DESIGN_DIR / "dominik-character.txt"
try:
    _CHARACTER_TEXT: str = _CHARACTER_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    raise RuntimeError(f"[onboarding_ai] Характер не найден: {_CHARACTER_PATH}")


# ── Constants ──────────────────────────────────────────────────────────────────

# Клички которые угадываем как собака
_DOG_NAMES = {
    "шарик", "бобик", "тузик", "рекс", "барон", "граф", "мухтар", "полкан",
    "арчи", "боб", "бакс", "зевс", "марс", "гектор", "барбос", "жучка",
    "найда", "лада", "альма", "дина", "ника", "белка", "пальма"
}

# Клички которые угадываем как кошка
_CAT_NAMES = {
    "мурка", "барсик", "рыжик", "пушок", "снежок", "китти", "муся",
    "кися", "пуся", "маруся", "васька", "тигрик", "лёва"
}

# Клички с явным мужским полом
_MALE_NAMES = {
    "рекс", "барон", "граф", "тузик", "бобик", "шарик", "мухтар", "полкан",
    "арчи", "боб", "бакс", "зевс", "марс", "гектор", "цезарь", "максимус",
    "брут", "барсик", "тигр", "тигрик", "кузя", "мурзик", "васька",
    "славик", "степан", "стёпа", "федя", "федор", "гриша", "серёга",
    "вася", "мишка", "колян", "витёк", "лёха", "санёк", "димон", "тёма",
    "юрик", "ромка", "антоха", "паша", "боря", "гена", "слава", "себастьян",
    "иннокентий", "аристарх", "архимед", "леонид", "николай", "александр",
    "максим", "дмитрий", "андрей", "сергей", "михаил", "алексей", "владимир"
}

# Клички с явным женским полом
_FEMALE_NAMES = {
    "мурка", "белка", "найда", "жучка", "дина", "ника", "альма", "пальма",
    "роза", "жасмин", "принцесса", "маркиза", "лейла", "багира", "муся",
    "кися", "пуся", "маруся", "дуся", "глаша", "снежинка", "ромашка",
    "лапочка", "милашка", "даша", "маша", "наташа", "катюша", "танюша",
    "оленька", "люся", "варя", "полина", "света", "лена", "соня", "аня",
    "настя", "вика", "юля", "ира", "нина", "галя", "зоя", "тоня"
}

# Кошачьи клички явно женского рода (для species_guess_cat preferred)
_FEMALE_CAT_NAMES = {"мурка", "муся", "кися", "пуся", "маруся", "дуся", "глаша"}

_NEUTRAL_NAMES = {
    "снежок", "облако", "персик", "солнышко",
    "пушок", "бублик", "рыжик", "малыш", "крошка",
}

_POPULAR_DOG_BREEDS = [
    "Лабрадор", "Овчарка", "Йорк", "Шпиц", "Такса",
    "Хаски", "Французский бульдог", "Корги", "Чихуахуа",
    "Метис", "Другая порода", "Не знаю породу",
]
_POPULAR_CAT_BREEDS = [
    "Британская", "Шотландская", "Мейн-кун", "Сфинкс",
    "Персидская", "Бенгальская", "Сиамская", "Русская голубая",
    "Абиссинская", "Беспородная", "Другая порода", "Не знаю породу",
]

_BREED_CLARIFICATIONS = {
    "овчарка": [
        "Немецкая овчарка", "Бельгийская малинуа", "Кавказская овчарка",
        "Среднеазиатская овчарка", "Австралийская овчарка", "Швейцарская овчарка",
    ],
    "йорк": ["Йоркширский терьер", "Бивер-йорк"],
    "шпиц": ["Померанский шпиц", "Немецкий шпиц", "Японский шпиц", "Финский шпиц"],
    "бульдог": ["Французский бульдог", "Английский бульдог", "Американский бульдог"],
    "такса": ["Стандартная такса", "Миниатюрная такса", "Кроличья такса"],
    "пудель": ["Той-пудель", "Карликовый пудель", "Малый пудель", "Королевский пудель"],
    "терьер": [
        "Джек-рассел-терьер", "Стаффордширский терьер", "Эрдельтерьер",
        "Вест-хайленд-уайт-терьер", "Скотч-терьер",
    ],
    "ретривер": ["Лабрадор-ретривер", "Золотистый ретривер", "Прямошёрстный ретривер"],
    "спаниель": ["Кокер-спаниель", "Кавалер-кинг-чарльз-спаниель", "Спрингер-спаниель"],
    "дог": ["Немецкий дог", "Аргентинский дог", "Бордоский дог"],
    "пинчер": ["Доберман", "Цвергпинчер", "Немецкий пинчер"],
    "лайка": ["Западно-сибирская лайка", "Восточно-сибирская лайка", "Русско-европейская лайка"],
    "сеттер": ["Ирландский сеттер", "Английский сеттер", "Шотландский сеттер"],
    "борзая": ["Русская псовая борзая", "Грейхаунд", "Уиппет", "Левретка"],
    "колли": ["Шотландская колли", "Бордер-колли", "Шелти"],
    "британская": ["Британская короткошёрстная", "Британская длинношёрстная"],
    "шотландская": ["Скоттиш-фолд", "Скоттиш-страйт", "Хайленд-фолд", "Хайленд-страйт"],
    "сфинкс": ["Канадский сфинкс", "Донской сфинкс", "Петерболд"],
    "персидская": ["Персидская классическая", "Экзотическая короткошёрстная"],
}


# ── Declension helper ─────────────────────────────────────────────────────────

def _decline_pet_name(name: str, case: str) -> str:
    """
    Склонение клички питомца.
    case: 'gen' (кого?), 'dat' (кому?), 'acc' (кого?),
          'inst' (кем?), 'prep' (о ком?)
    """
    if not name or name == "Питомец":
        forms = {
            "gen": "питомца", "dat": "питомцу", "acc": "питомца",
            "inst": "питомцем", "prep": "питомце",
        }
        return forms.get(case, name)

    if name.endswith("ка"):
        stem = name[:-2]
        forms = {
            "gen": f"{stem}ки", "dat": f"{stem}ке", "acc": f"{stem}ку",
            "inst": f"{stem}кой", "prep": f"{stem}ке",
        }
        return forms.get(case, name)

    if name.endswith("а"):
        stem = name[:-1]
        forms = {
            "gen": f"{stem}ы", "dat": f"{stem}е", "acc": f"{stem}у",
            "inst": f"{stem}ой", "prep": f"{stem}е",
        }
        return forms.get(case, name)

    if name.endswith("я"):
        stem = name[:-1]
        forms = {
            "gen": f"{stem}и", "dat": f"{stem}е", "acc": f"{stem}ю",
            "inst": f"{stem}ей", "prep": f"{stem}е",
        }
        return forms.get(case, name)

    if name.endswith("ь"):
        stem = name[:-1]
        forms = {
            "gen": f"{stem}я", "dat": f"{stem}ю", "acc": f"{stem}я",
            "inst": f"{stem}ем", "prep": f"{stem}е",
        }
        return forms.get(case, name)

    if name.endswith("й"):
        stem = name[:-1]
        forms = {
            "gen": f"{stem}я", "dat": f"{stem}ю", "acc": f"{stem}я",
            "inst": f"{stem}ем", "prep": f"{stem}е",
        }
        return forms.get(case, name)

    if name.endswith(("ко", "ло", "шко")):
        stem = name[:-1]
        forms = {
            "gen": f"{stem}а", "dat": f"{stem}у", "acc": f"{name}",
            "inst": f"{stem}ом", "prep": f"{stem}е",
        }
        return forms.get(case, name)

    forms = {
        "gen": f"{name}а", "dat": f"{name}у", "acc": f"{name}а",
        "inst": f"{name}ом", "prep": f"{name}е",
    }
    return forms.get(case, name)


# ── Parsing helpers ────────────────────────────────────────────────────────────

def _parse_age(msg: str) -> dict:
    """Уровень 1 — regex. Возвращает {"age_years": число, "birth_date": str, "parsed": bool}"""
    text = msg.lower().strip()
    year_match = re.search(r'(\d+)\s*(лет|год|года)', text)
    month_match = re.search(r'(\d+)\s*(месяц|месяца|месяцев)', text)
    half_year = "полгода" in text or "пол года" in text

    if year_match:
        return {"age_years": int(year_match.group(1)), "birth_date": None, "parsed": True}
    if month_match:
        months = int(month_match.group(1))
        return {"age_years": round(months / 12, 2), "birth_date": None, "parsed": True}
    if half_year:
        return {"age_years": 0.5, "birth_date": None, "parsed": True}
    return {"age_years": None, "birth_date": None, "parsed": False}


def _parse_age_with_gemini(msg: str, client) -> dict:
    """Уровень 2 — Gemini для нестандартных случаев."""
    today = datetime.now().strftime('%Y-%m-%d')
    prompt = (
        f'Пользователь написал о возрасте питомца: "{msg}"\n'
        f'Сегодня {today}. Верни ТОЛЬКО JSON без пояснений:\n'
        f'{{"age_years": <число 0-30 или null>, "birth_date": "<YYYY-MM-DD или null>"}}\n'
        f'Правила:\n'
        f'- "2 года" -> age_years 2\n'
        f'- "3 месяца" -> age_years 0.25\n'
        f'- "летом 2022" -> вычисли birth_date\n'
        f'- "совсем малыш" -> age_years 0.25\n'
        f'- непонятно -> оба null'
    )
    try:
        chat = client.chats.create(model="gemini-2.5-flash-lite")
        resp = chat.send_message(prompt)
        result = json.loads((resp.text or "").strip())
        result["parsed"] = True
        return result
    except Exception:
        return {"age_years": None, "birth_date": None, "parsed": False}


def _parse_name(msg: str, field: str) -> dict:
    """Уровень 1 — regex. Возвращает {"name": str, "is_valid": bool, "needs_ai": bool}"""
    text = msg.strip()
    lower = text.lower()

    if len(text) > 30:
        return {"name": None, "is_valid": False, "needs_ai": False}
    if any(c in lower for c in ["?", "зачем", "почему", "когда", "где"]):
        return {"name": None, "is_valid": False, "needs_ai": False}

    intro = ["меня зовут", "я ", "мне ", "моё имя", "мое имя", "называй меня"]
    if any(lower.startswith(p) for p in intro):
        return {"name": None, "is_valid": False, "needs_ai": True}

    if len(text.split()) > 3:
        return {"name": None, "is_valid": False, "needs_ai": True}

    words = text.split()
    if words:
        name = " ".join(w.capitalize() for w in words[:2])
        return {"name": name, "is_valid": True, "needs_ai": False}

    return {"name": None, "is_valid": False, "needs_ai": False}


def _parse_name_with_gemini(msg: str, field: str, client) -> dict:
    """Уровень 2 — Gemini для нестандартных случаев."""
    context = "имя владельца" if field == "owner_name" else "кличку питомца"
    prompt = (
        f'Пользователь написал: "{msg}"\n'
        f'Извлеки {context}. Верни ТОЛЬКО JSON:\n'
        f'{{"name": "<имя или null>", "is_valid": true/false}}\n'
        f'- "Меня зовут Александр" -> name "Александр", is_valid true\n'
        f'- "зачем вы спрашиваете" -> name null, is_valid false\n'
        f'- "Рекс 2" -> name "Рекс 2", is_valid true (кличка)\n'
        f'- Имя максимум 2 слова'
    )
    try:
        chat = client.chats.create(model="gemini-2.5-flash-lite")
        resp = chat.send_message(prompt)
        return json.loads((resp.text or "").strip())
    except Exception:
        return {"name": None, "is_valid": False}


def _detect_name_gender(pet_name: str, client) -> str:
    """Gemini определяет вероятный пол по кличке. Возвращает: male / female / neutral"""
    if not pet_name or not client:
        return "neutral"
    prompt = (
        f'Кличка питомца: "{pet_name}"\n'
        f'Определи вероятный пол для русскоязычной аудитории.\n'
        f'Ответь ТОЛЬКО одним словом: male, female, или neutral\n'
        f'"Рекс" -> male, "Мурка" -> female, "Себастьян" -> male, '
        f'"Персефона" -> female, "Кнопка" -> neutral'
    )
    try:
        chat = client.chats.create(model="gemini-2.5-flash-lite")
        resp = chat.send_message(prompt)
        result = (resp.text or "").strip().lower()
        return result if result in ("male", "female", "neutral") else "neutral"
    except Exception:
        return "neutral"


def _parse_breed_with_gemini(msg: str, species: str, client) -> dict:
    """AI-first парсинг породы."""
    animal = "собаки" if "dog" in (species or "") else "кошки"
    prompt = (
        f'Пользователь написал название породы {animal}: "{msg}"\n'
        f'Верни ТОЛЬКО JSON без пояснений:\n'
        f'Если это точная порода или понятное сокращение:\n'
        f'{{"breed": "Точное полное название", "needs_clarification": false}}\n'
        f'Если нужно уточнить подвид (например "ретривер" — золотистый или лабрадор?):\n'
        f'{{"breed": null, "needs_clarification": true, "options": ["вариант1", "вариант2", "вариант3"]}}\n'
        f'Примеры:\n'
        f'"Йорк" -> {{"breed": "Йоркширский терьер", "needs_clarification": false}}\n'
        f'"бивер йорк" -> {{"breed": "Бивер-йорк", "needs_clarification": false}}\n'
        f'"лабрадор" -> {{"breed": null, "needs_clarification": true, '
        f'"options": ["Лабрадор-ретривер", "Золотистый ретривер"]}}\n'
        f'"немецкая" -> {{"breed": "Немецкая овчарка", "needs_clarification": false}}\n'
        f'"помесь шпица" -> {{"breed": "Метис/помесь шпица", "needs_clarification": false}}\n'
        f'"дворняга" -> {{"breed": "Метис", "needs_clarification": false}}'
    )
    try:
        chat = client.chats.create(model="gemini-2.5-flash-lite")
        resp = chat.send_message(prompt)
        return json.loads((resp.text or "").strip())
    except Exception:
        return {"breed": msg.strip().capitalize(), "needs_clarification": False}


# ── Step logic ─────────────────────────────────────────────────────────────────

def _get_current_step(collected: dict) -> str:
    """Determine current onboarding step based on collected data."""

    if not collected.get("owner_name"):
        return "owner_name"

    if not collected.get("pet_name"):
        return "pet_name"

    # Угадывание вида — ТОЛЬКО для явных животных кличек
    if not collected.get("species") and not collected.get("_species_guessed"):
        name = (collected.get("pet_name") or "").lower().strip()
        if name in _DOG_NAMES:
            return "species_guess_dog"
        if name in _CAT_NAMES:
            return "species_guess_cat"
        # Человеческие / нейтральные клички — НЕ угадываем, идём к goal

    if not collected.get("goal"):
        return "goal"

    # concern УБРАН — тревога обрабатывается в финале

    # Вид — если не определён через угадывание
    if not collected.get("species"):
        return "species"

    # Паспорт — между species и breed
    if not collected.get("_passport_skipped") and not collected.get("breed"):
        return "passport_offer"

    # Порода — один шаг, без subcategory
    if not collected.get("breed"):
        return "breed"

    # Дата рождения / возраст
    if (
        not collected.get("birth_date")
        and not collected.get("age_years")
        and not collected.get("_age_skipped")
    ):
        return "birth_date"

    # Пол — пропускается для кошек (уже определён при выборе Кот/Кошка)
    if not collected.get("gender"):
        return "gender"

    # Кастрация
    if collected.get("is_neutered") is None and not collected.get("_neutered_skipped"):
        return "is_neutered"

    # Аватар
    if not collected.get("avatar_url") and not collected.get("_avatar_skipped"):
        return "avatar"

    return "complete"


def _get_step_quick_replies(step: str, collected: dict, client=None) -> list:
    """Return quick reply buttons for current step."""

    if step == "owner_name":
        return []

    if step == "pet_name":
        return []

    if step == "species_guess_dog":
        return [
            {"label": "Да, пёс", "value": "Да, пёс", "preferred": True},
            {"label": "Не угадал", "value": "Не угадал", "preferred": False},
        ]

    if step == "species_guess_cat":
        name = (collected.get("pet_name") or "").lower().strip()
        if name in _FEMALE_CAT_NAMES:
            return [
                {"label": "Кошка", "value": "Кошка", "preferred": True},
                {"label": "Кот", "value": "Кот", "preferred": False},
                {"label": "Не угадал", "value": "Не угадал", "preferred": False},
            ]
        return [
            {"label": "Кот", "value": "Кот", "preferred": True},
            {"label": "Кошка", "value": "Кошка", "preferred": False},
            {"label": "Не угадал", "value": "Не угадал", "preferred": False},
        ]

    if step == "goal":
        return [
            {"label": "Слежу за здоровьем", "value": "Слежу за здоровьем", "preferred": False},
            {"label": "Прививки и плановое", "value": "Прививки и плановое", "preferred": False},
            {"label": "Веду дневник", "value": "Веду дневник", "preferred": False},
            {"label": "Кое-что беспокоит", "value": "Кое-что беспокоит", "preferred": False},
        ]

    # concern УБРАН

    if step == "species":
        return [
            {"label": "Кот", "value": "Кот", "preferred": False},
            {"label": "Кошка", "value": "Кошка", "preferred": False},
            {"label": "Собака", "value": "Собака", "preferred": False},
        ]

    if step == "passport_offer":
        return [
            {"label": "Сфотографирую", "value": "Сфотографирую", "preferred": True},
            {"label": "Лучше вручную", "value": "Лучше вручную", "preferred": False},
            {"label": "Паспорта нет", "value": "Паспорта нет", "preferred": False},
        ]

    if step == "breed":
        species = collected.get("species", "dog")
        if collected.get("_breed_unknown"):
            return [
                {"label": "Загрузить фото", "value": "BREED_PHOTO", "preferred": True},
                {"label": "Пропустить", "value": "Пропустить", "preferred": False},
            ]
        if collected.get("_breed_photo_requested"):
            return []
        if collected.get("_breed_clarification_options"):
            opts = collected["_breed_clarification_options"]
            qr = [
                {"label": o, "value": o, "preferred": i == 0}
                for i, o in enumerate(opts[:6])
            ]
            qr.append({"label": "Другая порода", "value": "Другая порода", "preferred": False})
            return qr
        if collected.get("_awaiting_breed_text"):
            return []
        popular = _POPULAR_DOG_BREEDS if species == "dog" else _POPULAR_CAT_BREEDS
        return [
            {"label": b, "value": b, "preferred": False}
            for b in popular
        ]

    if step == "birth_date":
        if collected.get("_age_approximate"):
            return []
        return [
            {"label": "Выбрать дату", "value": "Выбрать дату", "preferred": True},
            {"label": "Примерный возраст", "value": "Примерный возраст", "preferred": False},
            {"label": "Не знаю", "value": "Не знаю", "preferred": False},
        ]

    if step == "gender":
        hint = collected.get("_detected_gender_hint", "neutral")
        name = (collected.get("pet_name") or "").lower().strip()
        if name in _NEUTRAL_NAMES or hint == "neutral":
            return [
                {"label": "Мальчик", "value": "Мальчик", "preferred": False},
                {"label": "Девочка", "value": "Девочка", "preferred": False},
            ]
        if hint == "male":
            return [
                {"label": "Да, мальчик", "value": "Да, мальчик", "preferred": True},
                {"label": "Нет, девочка", "value": "Нет, девочка", "preferred": False},
            ]
        if hint == "female":
            return [
                {"label": "Да, девочка", "value": "Да, девочка", "preferred": True},
                {"label": "Нет, мальчик", "value": "Нет, мальчик", "preferred": False},
            ]
        return [
            {"label": "Мальчик", "value": "Мальчик", "preferred": False},
            {"label": "Девочка", "value": "Девочка", "preferred": False},
        ]

    if step == "is_neutered":
        return [
            {"label": "Да", "value": "Да", "preferred": False},
            {"label": "Нет", "value": "Нет", "preferred": False},
        ]

    if step == "avatar":
        return [
            {"label": "Загрузить фото", "value": "AVATAR_PHOTO", "preferred": True},
            {"label": "Пропустить", "value": "Пропустить", "preferred": False},
        ]

    return []


def _get_step_instruction(step: str, collected: dict) -> str:
    """Return Gemini instruction for current step. Exact texts with declensions."""
    owner = collected.get("owner_name", "")
    pet = collected.get("pet_name", "")
    species = collected.get("species", "")
    breed = collected.get("breed", "")
    gender = collected.get("gender", "")
    hint = collected.get("_detected_gender_hint", "neutral")

    pet_gen = _decline_pet_name(pet, "gen")
    pet_dat = _decline_pet_name(pet, "dat")

    if step == "owner_name":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?"\n'
            f"ЗАПРЕЩЕНО менять текст, добавлять слова, задавать другие вопросы."
        )

    if step == "pet_name":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{owner}, как зовут питомца?"\n'
            f"ЗАПРЕЩЕНО: 'Приятно познакомиться', два предложения, любые другие вопросы."
        )

    if step == "species_guess_dog":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} — ставлю на собаку. Угадал?"\n'
            f"ЗАПРЕЩЕНО: порода, возраст, пол."
        )

    if step == "species_guess_cat":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} — ставлю на кота. Угадал?"\n'
            f"ЗАПРЕЩЕНО: порода, возраст, пол."
        )

    if step == "goal":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet_dat} повезло с хозяином. Чем могу помочь?"\n'
            f"ЗАПРЕЩЕНО: вид, порода, возраст, пол, 'С чего начнём'."
        )

    # concern УБРАН

    if step == "species":
        goal = collected.get("goal", "")
        if collected.get("_exotic_attempt"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Пока работаю только с кошками и собаками. Кошка или собака есть?"\n'
                f"ЗАПРЕЩЕНО: любые другие темы."
            )
        if goal == "Есть тревога":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Чтобы разобраться — пара вопросов. Кошка или собака?"\n'
                f"ЗАПРЕЩЕНО: порода, возраст, пол."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Кошка или собака?"\n'
            f"ЗАПРЕЩЕНО: порода, возраст, пол."
        )

    if step == "passport_offer":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу в карточку."\n'
            f"ЗАПРЕЩЕНО: порода, метис, возраст, пол, кастрация — НИ СЛОВА."
        )

    if step == "breed":
        if collected.get("_breed_unknown"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Загрузи фото {pet_gen} — определю породу сам. Или пропускаем."\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if collected.get("_breed_photo_requested"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Жду фото — отправь прямо сюда."\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if collected.get("_breed_clarification_options"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Уточни — какая именно?"\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if collected.get("_awaiting_breed_text"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Пиши — какая порода?"\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if species == "dog":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Какая порода у {pet_gen}?"\n'
                f"ЗАПРЕЩЕНО: возраст, пол, кастрация, дата рождения."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Какая порода у {pet_gen}?"\n'
            f"ЗАПРЕЩЕНО: возраст, пол, кастрация, дата рождения."
        )

    if step == "birth_date":
        if breed and not collected.get("_age_approximate"):
            return (
                f"Начни с ОДНОГО короткого интересного факта о породе {breed} (максимум 8 слов). "
                f'Потом спроси: "Когда родился {pet}?"\n'
                f"ЗАПРЕЩЕНО: пол, кастрация, второй вопрос.\n"
                f'ПРИМЕР: "Йорки — маленькие с характером на большую собаку. Когда родился {pet}?"'
            )
        if collected.get("_age_approximate"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Сколько примерно — в годах или месяцах?"\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Когда родился {pet}?"\n'
            f"ЗАПРЕЩЕНО: пол, кастрация, порода."
        )

    if step == "gender":
        age_reaction = ""
        age = collected.get("age_years")
        if age is not None and not collected.get("_age_reacted"):
            if age < 1:
                age_reaction = "Совсем малыш ещё. "
            elif age <= 2:
                age_reaction = "Энергии на десятерых. "
            elif age <= 5:
                age_reaction = "Золотые годы — сил полно, характер сложился. "
            elif age <= 8:
                age_reaction = "Зрелый, спокойный, знает чего хочет. "
            elif age <= 11:
                age_reaction = "Мудрый. Такие всё понимают без слов. "
            else:
                age_reaction = "Столько лет вместе — это настоящая история. "

        if hint == "male":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "{age_reaction}{pet} — мальчик?"\n'
                f"ЗАПРЕЩЕНО: кастрация, порода, повторять возраст числом."
            )
        if hint == "female":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "{age_reaction}{pet} — девочка?"\n'
                f"ЗАПРЕЩЕНО: кастрация, порода, повторять возраст числом."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{age_reaction}{pet} — мальчик или девочка?"\n'
            f"ЗАПРЕЩЕНО: кастрация, порода, повторять возраст числом."
        )

    if step == "is_neutered":
        word = "стерилизована" if gender == "female" else "кастрирован"
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} {word}?"\n'
            f"ЗАПРЕЩЕНО: любые другие вопросы."
        )

    if step == "avatar":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Последний штрих — фото {pet_gen} для профиля."\n'
            f"ЗАПРЕЩЕНО: любые другие вопросы."
        )

    return f"Ответь коротко про {pet}."


# ── System prompt ──────────────────────────────────────────────────────────────

def _build_system_prompt(
    collected: dict,
    step_instruction: str,
    current_step: str = "",
    quick_replies: list = None,
) -> str:

    # --- Заполненные поля ---
    field_labels = {
        "owner_name": "Владелец",
        "pet_name": "Кличка",
        "species": "Вид",
        "breed": "Порода",
        "birth_date": "Дата рождения",
        "age_years": "Возраст (лет)",
        "gender": "Пол",
        "is_neutered": "Кастрирован/стерилизован",
        "goal": "Цель",
    }
    known_lines = []
    for key, label in field_labels.items():
        val = collected.get(key)
        if val is not None and val != "" and val != "null":
            known_lines.append(f"  {label}: {val}")
    known_block = "\n".join(known_lines) if known_lines else "  пока ничего"

    # --- Тон по goal ---
    goal = collected.get("goal", "")
    tone_map = {
        "Есть тревога": "ТОНАЛЬНОСТЬ: спокойный, без давления, врач-друг.",
        "Слежу за здоровьем": "ТОНАЛЬНОСТЬ: профилактический, деловой.",
        "Прививки и плановое": "ТОНАЛЬНОСТЬ: чёткий, конкретный.",
        "Веду дневник": "ТОНАЛЬНОСТЬ: тёплый, без срочности.",
    }
    tone = tone_map.get(goal, "")

    # --- Контекст ---
    ctx = []
    if tone:
        ctx.append(tone)
    if collected.get("_concern_heard"):
        ctx.append("Пользователь рассказал о тревоге — в финале вернись к ней.")
    ctx_block = ("\n" + "\n".join(ctx) + "\n") if ctx else ""

    # --- Кнопки ---
    if quick_replies:
        labels = ", ".join(qr["label"] for qr in quick_replies)
        btn = (
            f"\nПод твоим сообщением будут кнопки: {labels}."
            f"\nЗАПРЕЩЕНО копировать названия кнопок в текст."
            f"\nЗАПРЕЩЕНО перечислять варианты в скобках, через слэш или через 'или'."
        )
    else:
        btn = "\nКнопок нет — пользователь ответит текстом."

    # --- Склонения ---
    pet_name = collected.get("pet_name", "")
    if pet_name and pet_name != "Питомец":
        decl = (
            f"\nГОТОВЫЕ СКЛОНЕНИЯ (используй только их, НЕ придумывай свои):\n"
            f"  {pet_name} -> кого? {_decline_pet_name(pet_name, 'gen')}"
            f" / кому? {_decline_pet_name(pet_name, 'dat')}"
            f" / кем? {_decline_pet_name(pet_name, 'inst')}"
            f" / о ком? {_decline_pet_name(pet_name, 'prep')}\n"
        )
    else:
        decl = ""

    # --- Сборка ---
    return (
        f"{_CHARACTER_TEXT.strip()}\n"
        f"\n---\n"
        f"\nУЖЕ ИЗВЕСТНО:\n{known_block}\n"
        f"{ctx_block}"
        f"{decl}"
        f"\n=== ЖЕЛЕЗНЫЕ ПРАВИЛА ===\n"
        f"1. Скажи РОВНО тот текст который указан в задаче — не добавляй слова\n"
        f"2. ОДИН вопрос, ОДНО-ДВА предложения максимум\n"
        f"3. НОЛЬ emoji\n"
        f"4. НИКОГДА не произноси: Понял, Отлично, Прекрасно, Замечательно, "
        f"Зафиксировал, Конечно, Разумеется, Рад помочь, С чего начнём, "
        f"Хорошо, Приятно познакомиться, Давай начнём\n"
        f"5. НЕ используй имя Dominik вместо клички питомца\n"
        f"=========================\n"
        f"\nТВОЯ ЗАДАЧА:\n{step_instruction}"
        f"{btn}\n"
    )


# ── Stop-phrase filter ─────────────────────────────────────────────────────────

def _remove_stop_phrases(text: str) -> str:
    """Удаляет стоп-слова из начала ответа Gemini."""
    stop_starts = [
        r'^Я понял[,\.]?\s*',
        r'^Понял[,\.]?\s*',
        r'^Отлично[,\.]?\s*',
        r'^Хорошо[,\.]?\s*',
        r'^Ясно[,\.]?\s*',
        r'^Замечательно[,\.]?\s*',
        r'^Прекрасно[,\.]?\s*',
        r'^Зафиксировал[,\.]?\s*',
        r'^Конечно[,\.]?\s*',
    ]
    for pattern in stop_starts:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
    return text


# ── Fallback text ──────────────────────────────────────────────────────────────

def _get_fallback_text(step: str, collected: dict) -> str:
    pet = collected.get("pet_name", "питомец")
    pet_gen = _decline_pet_name(pet, "gen")
    pet_dat = _decline_pet_name(pet, "dat")
    owner = collected.get("owner_name", "")
    fallbacks = {
        "owner_name": "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?",
        "pet_name": f"{owner}, как зовут питомца?" if owner else "Как зовут питомца?",
        "species_guess_dog": f"{pet} — ставлю на собаку. Угадал?",
        "species_guess_cat": f"{pet} — ставлю на кота. Угадал?",
        "goal": f"{pet_dat} повезло с хозяином. Чем могу помочь?",
        "species": "Кошка или собака?",
        "passport_offer": "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу.",
        "breed": f"Какая порода у {pet_gen}?",
        "birth_date": f"Когда родился {pet}?",
        "gender": f"{pet} — мальчик или девочка?",
        "is_neutered": f"{pet} кастрирован?",
        "avatar": f"Последний штрих — фото {pet_gen} для профиля.",
    }
    return fallbacks.get(step, f"Расскажи мне про {pet}.")


# ── User input parser ─────────────────────────────────────────────────────────

def _parse_user_input(msg: str, step: str, collected: dict, client=None) -> dict:
    if not msg or not msg.strip():
        return {}

    raw = msg.strip()
    low = raw.lower()
    clean = low.rstrip(".,!?;:\u2026")
    updates: dict = {}

    # ─── owner_name ───
    if step == "owner_name":
        if any(w in low for w in ["не скажу", "аноним", "не хочу", "не твоё дело", "не твое дело"]):
            updates["owner_name"] = "Друг"
            return updates
        if re.match(r"^[\d\W]+$", raw):
            return {}
        parsed = _parse_name(raw, "owner_name")
        if parsed.get("is_valid") and parsed.get("name"):
            updates["owner_name"] = parsed["name"]
        elif parsed.get("needs_ai") and client:
            ai = _parse_name_with_gemini(raw, "owner_name", client)
            if ai.get("is_valid") and ai.get("name"):
                updates["owner_name"] = ai["name"]
        if not updates.get("owner_name") and len(raw) <= 20:
            updates["owner_name"] = raw.strip().split()[0].capitalize()

    # ─── pet_name ───
    elif step == "pet_name":
        if any(w in low for w in ["не знаю", "нет имени", "без имени", "пока нет"]):
            updates["pet_name"] = "Питомец"
            return updates
        if re.match(r"^[\d\W]+$", raw):
            return {}
        parsed = _parse_name(raw, "pet_name")
        if parsed.get("is_valid") and parsed.get("name"):
            updates["pet_name"] = parsed["name"]
        elif parsed.get("needs_ai") and client:
            ai = _parse_name_with_gemini(raw, "pet_name", client)
            if ai.get("is_valid") and ai.get("name"):
                updates["pet_name"] = ai["name"]
        if not updates.get("pet_name") and len(raw) <= 30:
            updates["pet_name"] = raw.strip().split()[0].capitalize()

    # ─── species_guess_dog ───
    elif step == "species_guess_dog":
        if any(w in clean for w in ["да", "пёс", "пес", "собака", "угадал"]):
            updates["species"] = "dog"
        else:
            updates["_species_guessed"] = True

    # ─── species_guess_cat ───
    elif step == "species_guess_cat":
        if "кошка" in clean:
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif "кот" in clean.split() or clean in ("кот", "да кот", "да, кот"):
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif any(w in clean for w in ["да", "угадал"]):
            updates["species"] = "cat"
            updates["gender"] = "male"
        else:
            updates["_species_guessed"] = True

    # ─── goal ───
    elif step == "goal":
        goal_map = {
            "слежу за здоровьем": "Слежу за здоровьем",
            "прививки и плановое": "Прививки и плановое",
            "веду дневник": "Веду дневник",
            "кое-что беспокоит": "Есть тревога",
            "кое что беспокоит": "Есть тревога",
            "беспокоит": "Есть тревога",
            "тревога": "Есть тревога",
            "тревожит": "Есть тревога",
            "болеет": "Есть тревога",
            "болит": "Есть тревога",
            "плохо": "Есть тревога",
            "здоровь": "Слежу за здоровьем",
            "привив": "Прививки и плановое",
            "вакцин": "Прививки и плановое",
            "дневник": "Веду дневник",
            "записи": "Веду дневник",
        }
        for key, value in goal_map.items():
            if key in low:
                updates["goal"] = value
                break
        if not updates.get("goal") and len(raw) > 2:
            updates["goal"] = raw
        if updates.get("goal") == "Есть тревога":
            updates["_concern_heard"] = True

    # ─── concern УБРАН ───

    # ─── species ───
    elif step == "species":
        if clean == "кот" or clean.startswith("кот "):
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif "кошка" in clean:
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif any(w in clean for w in ["собака", "пёс", "пес", "щенок"]):
            updates["species"] = "dog"
        else:
            exotic = [
                "попугай", "хомяк", "рыбка", "черепаха", "кролик",
                "крыса", "морская свинка", "хорёк", "хорек",
                "ящерица", "змея", "шиншилла", "птица", "канарейка",
                "игуана", "хамелеон", "паук", "улитка",
            ]
            if any(w in low for w in exotic):
                updates["_exotic_attempt"] = True

    # ─── passport_offer ───
    elif step == "passport_offer":
        if "сфотографирую" in low:
            updates["_passport_photo_requested"] = True
        elif any(w in low for w in [
            "вручную", "паспорта нет", "нет паспорта",
            "лучше вручную", "нет", "без паспорта", "пропуст",
        ]):
            updates["_passport_skipped"] = True

    # ─── breed ───
    elif step == "breed":
        if any(w in low for w in ["не знаю породу", "не знаю", "хз", "без понятия"]):
            updates["_breed_unknown"] = True
            return updates
        if "другая порода" in low:
            updates["_breed_clarification_options"] = None
            updates["_awaiting_breed_text"] = True
            return updates
        if clean in ("пропустить", "пропуск", "скип"):
            updates["breed"] = "Метис"
            return updates
        if raw == "BREED_PHOTO":
            updates["_breed_photo_requested"] = True
            return updates
        metis_words = [
            "дворняга", "дворняжка", "метис", "беспородная",
            "беспородный", "дворняга или метис", "двортерьер",
            "помесь", "смесь",
        ]
        if any(w in low for w in metis_words):
            updates["breed"] = "Метис"
            return updates

        # === УРОВЕНЬ 0: Словарь подвидов ===
        clarify = _BREED_CLARIFICATIONS.get(clean)
        if not clarify:
            for key in _BREED_CLARIFICATIONS:
                if clean.startswith(key) or key.startswith(clean):
                    clarify = _BREED_CLARIFICATIONS[key]
                    break
        if clarify:
            updates["_breed_clarification_options"] = clarify
            return updates

        # === УРОВЕНЬ 1: Rapidfuzz (порог 85%) ===
        best_match = None
        best_score = 0
        for breed_name in ALL_BREEDS:
            score = fuzz.ratio(low, breed_name.lower())
            if score > best_score:
                best_score = score
                best_match = breed_name

        if best_score >= 85 and best_match:
            match_lower = best_match.lower()
            for key in _BREED_CLARIFICATIONS:
                if key in match_lower or match_lower.startswith(key):
                    updates["_breed_clarification_options"] = _BREED_CLARIFICATIONS[key]
                    return updates
            updates["breed"] = best_match
            return updates

        # === УРОВЕНЬ 2: AI парсинг ===
        if client:
            result = _parse_breed_with_gemini(raw, collected.get("species", "dog"), client)
            if result.get("breed"):
                breed_low = result["breed"].lower()
                for key in _BREED_CLARIFICATIONS:
                    if key in breed_low or breed_low.startswith(key):
                        updates["_breed_clarification_options"] = _BREED_CLARIFICATIONS[key]
                        return updates
                updates["breed"] = result["breed"]
            elif result.get("needs_clarification") and result.get("options"):
                updates["_breed_clarification_options"] = result["options"]

    # ─── birth_date ───
    elif step == "birth_date":
        if clean in ("выбрать дату", "знаю дату рождения", "знаю дату"):
            updates["_wants_date_picker"] = True
            return updates
        if clean in ("примерный возраст", "примерно"):
            updates["_age_approximate"] = True
            updates["_wants_date_picker"] = False
            return updates
        if clean in ("не знаю", "хз", "без понятия"):
            updates["_age_skipped"] = True
            updates["_wants_date_picker"] = False
            return updates
        updates["_wants_date_picker"] = False
        updates["_age_approximate"] = False
        date_match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", raw.strip())
        if date_match:
            day, month, year = date_match.groups()
            try:
                bd = date(int(year), int(month), int(day))
                today = date.today()
                if bd > today:
                    return {}
                if (today.year - bd.year) > 30:
                    return {}
                updates["birth_date"] = f"{year}-{month}-{day}"
                age = today.year - bd.year - (
                    (today.month, today.day) < (bd.month, bd.day)
                )
                updates["age_years"] = age
            except (ValueError, TypeError):
                return {}
            return updates
        date_match2 = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw.strip())
        if date_match2:
            year, month, day = date_match2.groups()
            try:
                bd = date(int(year), int(month), int(day))
                today = date.today()
                if bd > today or (today.year - bd.year) > 30:
                    return {}
                updates["birth_date"] = f"{year}-{month}-{day}"
                age = today.year - bd.year - (
                    (today.month, today.day) < (bd.month, bd.day)
                )
                updates["age_years"] = age
            except (ValueError, TypeError):
                return {}
            return updates
        age_result = _parse_age(raw)
        if age_result:
            updates.update(age_result)
        elif client:
            age_result = _parse_age_with_gemini(raw, client)
            if age_result:
                updates.update(age_result)

    # ─── gender ───
    elif step == "gender":
        if any(w in clean for w in ["мальчик", "кобель", "самец", "пацан", "парень", "мальч"]):
            updates["gender"] = "male"
        elif any(w in clean for w in ["девочка", "сука", "самка", "девоч"]):
            updates["gender"] = "female"
        elif clean in ("да", "ага", "верно", "точно", "угу", "да да", "ну да"):
            hint = collected.get("_detected_gender_hint", "neutral")
            if hint == "male":
                updates["gender"] = "male"
            elif hint == "female":
                updates["gender"] = "female"
        elif clean in ("нет", "не", "неа"):
            hint = collected.get("_detected_gender_hint", "neutral")
            if hint == "male":
                updates["gender"] = "female"
            elif hint == "female":
                updates["gender"] = "male"

    # ─── is_neutered ───
    elif step == "is_neutered":
        if clean in ("да", "ага", "угу", "кастрирован", "стерилизована",
                      "кастрирована", "стерилизован", "давно", "да давно"):
            updates["is_neutered"] = True
        elif clean in ("нет", "не", "неа", "нет ещё", "нет еще", "пока нет"):
            updates["is_neutered"] = False

    # ─── avatar ───
    elif step == "avatar":
        if raw == "AVATAR_PHOTO":
            pass
        elif any(w in low for w in [
            "пропустить", "пропуск", "потом", "позже",
            "не сейчас", "скип", "нет", "не хочу",
        ]):
            updates["_avatar_skipped"] = True

    return updates


# ── Pet creation ───────────────────────────────────────────────────────────────

def _create_pet(user_id: str, collected: dict) -> tuple[str, int | None] | None:
    """Create pet in supabase from collected data. Returns (pet_id, short_id) or None."""
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
        short_id = result.data[0].get("short_id")
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

    return pet_id, short_id


# ── Chat persistence ──────────────────────────────────────────────────────────

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


# ── Pet card & completion text ─────────────────────────────────────────────────

def _build_pet_card(collected: dict, pet_id: str, short_id: int | None = None) -> dict:
    # NOTE: Временно не вызывается (pet_card=None в complete).
    # Сохранена для будущего walkthrough компонента. Не удалять.
    """Build pet card dict for UI response."""
    species_raw = (collected.get("species") or "").lower()
    species_display = "Кошка" if "cat" in species_raw or "кош" in species_raw or "кот" in species_raw else "Собака"

    gender_raw = (collected.get("gender") or "").lower()
    if any(w in gender_raw for w in ["female", "девочк", "самка"]):
        gender_display = "Самка"
    elif any(w in gender_raw for w in ["male", "мальчик", "самец"]):
        gender_display = "Самец"
    else:
        gender_display = collected.get("gender") or "\u2014"

    neutered_raw = str(collected.get("is_neutered") or "").lower()
    neutered_display = "Да" if neutered_raw in {"да", "yes", "true", "1", "кастрирован", "стерилизован", "стерилизована"} else "Нет"

    age_display = "\u2014"
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

    species_en = "Dog" if "dog" in species_raw else "Cat" if "cat" in species_raw else ""
    gender_en = "Male" if gender_display == "Самец" else "Female" if gender_display == "Самка" else ""
    neutered_en = "Yes" if neutered_display == "Да" else "No"

    return {
        "id": pet_id,
        "short_id": short_id,
        "name": collected.get("pet_name") or "Питомец",
        "species": species_display,
        "species_en": species_en,
        "breed": collected.get("breed") or "\u2014",
        "breed_en": BREED_EN.get(collected.get("breed") or "", collected.get("breed") or "\u2014"),
        "gender": gender_display,
        "gender_en": gender_en,
        "age": age_display,
        "neutered": neutered_display,
        "neutered_en": neutered_en,
        "avatar_url": collected.get("avatar_url"),
    }


def _build_completion_text(collected: dict) -> str:
    """Generate completion text based on goal. No Gemini needed."""
    pet = collected.get("pet_name") or "питомца"
    goal = collected.get("goal") or ""

    if "тревог" in goal.lower() or goal == "Есть тревога":
        return (
            f"Карточка готова. "
            f"Теперь расскажи — что беспокоит {pet}?"
        )
    elif "здоровь" in goal.lower():
        return (
            f"Всё на месте. "
            f"Открой профиль {pet} — там уже всё что ты рассказал."
        )
    elif "привив" in goal.lower():
        return (
            f"Готово. Профиль {pet} создан — загляни туда."
        )
    elif "дневник" in goal.lower():
        return (
            f"Карточка {pet} готова. Пиши мне когда нужно."
        )
    else:
        return f"Карточка {pet} готова. Открой профиль — там уже всё основное."


# ── Main handler ───────────────────────────────────────────────────────────────

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
    collected: dict = user_flags.get("onboarding_collected") or {}

    # 2. Handle special inputs (OCR, breed detection, avatar)
    actual_message = message_text
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # 2a. Passport OCR
    if passport_ocr_data and passport_ocr_data.get("success") and passport_ocr_data.get("confidence", 0) >= 0.6:
        ocr_fields = {"pet_name", "breed", "birth_date", "gender", "is_neutered"}
        ocr_updates = {f: passport_ocr_data[f] for f in ocr_fields if passport_ocr_data.get(f) and not collected.get(f)}
        collected.update(ocr_updates)
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

    # 3. First _get_current_step — before parsing
    current_step = _get_current_step(collected)
    logger.info("[ONB] BEFORE step=%s msg='%s' collected_keys=%s", current_step, actual_message[:50] if actual_message else "", [k for k in collected if not k.startswith("_")])

    # 4. If step is gender — compute hint BEFORE everything else
    if current_step == "gender" and not collected.get("_detected_gender_hint"):
        pet_name_val = collected.get("pet_name", "")
        name_lower = pet_name_val.lower()
        if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
            collected["_detected_gender_hint"] = "male"
        elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
            collected["_detected_gender_hint"] = "female"
        else:
            collected["_detected_gender_hint"] = _detect_name_gender(pet_name_val, client)

    # 5. Parse user input (text messages only, not special inputs)
    if actual_message and actual_message == message_text:
        updates = _parse_user_input(actual_message, current_step, collected, client=client)
        collected.update(updates)
        logger.info("[ONB] PARSED updates=%s", updates)

    # Сброс одноразовых флагов
    if collected.get("birth_date") or collected.get("age_years") or collected.get("_age_skipped"):
        collected["_wants_date_picker"] = False
        collected["_age_approximate"] = False

    # 6. Second _get_current_step — after parsing
    current_step = _get_current_step(collected)
    logger.info("[ONB] AFTER step=%s flags=%s", current_step, {k: v for k, v in collected.items() if k.startswith("_")})

    # 7. If step changed to gender — compute hint for new step
    if current_step == "gender" and not collected.get("_detected_gender_hint"):
        pet_name_val = collected.get("pet_name", "")
        name_lower = pet_name_val.lower()
        if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
            collected["_detected_gender_hint"] = "male"
        elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
            collected["_detected_gender_hint"] = "female"
        else:
            collected["_detected_gender_hint"] = _detect_name_gender(pet_name_val, client)

    # 8. Save user message
    user_chat_id = None
    if actual_message and actual_message.strip():
        user_chat_id = _save_user_message(user_id, actual_message)

    # 9. Save collected to flags (before any early return)
    user_flags["onboarding_collected"] = collected
    update_user_flags(user_id, user_flags)

    # 10. Check completion — early return without Gemini
    if current_step == "complete":
        create_result = _create_pet(user_id, collected)
        if create_result:
            pet_id, short_id = create_result
            user_flags["onboarding_collected"] = None
            user_flags["onboarding_pet_id"] = pet_id
            update_user_flags(user_id, user_flags)

            pet_card = None  # TODO: заменить на walkthrough
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

    # === DatePicker early return — НЕ вызываем AI ===
    if current_step == "birth_date" and collected.get("_wants_date_picker"):
        user_flags["onboarding_collected"] = collected
        update_user_flags(user_id, user_flags)

        return JSONResponse(content={
            "ai_response": "",
            "quick_replies": [],
            "onboarding_phase": "collecting",
            "pet_id": None,
            "pet_card": None,
            "input_type": "date_picker",
            "collected": collected,
        })

    # 11. Compute quick replies (once)
    quick_replies = _get_step_quick_replies(current_step, collected, client)

    # 12. Compute step instruction
    step_instruction = _get_step_instruction(current_step, collected)

    # 13. Build system prompt
    system_prompt = _build_system_prompt(
        collected, step_instruction, current_step, quick_replies
    )

    # 14. Call OpenAI GPT-4o-mini — text only
    try:
        oai_client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

        history_rows = _load_chat_history(user_id, limit=20)
        oai_messages = [{"role": "system", "content": system_prompt}]
        for row in history_rows:
            role = "assistant" if row["role"] == "ai" else "user"
            content = row.get("message") or ""
            if content:
                oai_messages.append({"role": role, "content": content})
        oai_messages.append({"role": "user", "content": actual_message or "Начни онбординг"})

        response = oai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=oai_messages,
            max_tokens=150,
            temperature=0.3,
        )
        ai_text = (response.choices[0].message.content or "").strip()
        ai_text = _remove_stop_phrases(ai_text)
    except Exception as e:
        logger.error("[oai_call] %s", e)
        ai_text = ""

    # 15. Fallback if empty response
    if not ai_text:
        ai_text = _get_fallback_text(current_step, collected)

    # 15b. Set _age_reacted after gender step uses age reaction
    if current_step == "gender" and collected.get("age_years") is not None:
        collected["_age_reacted"] = True
        user_flags["onboarding_collected"] = collected
        update_user_flags(user_id, user_flags)

    # 16. Save AI response
    _save_ai_message(user_id, ai_text, None, user_chat_id)

    # 17. Return response
    input_type = "date_picker" if (current_step == "birth_date" and collected.get("_wants_date_picker")) else "text"
    logger.info("[ONB] RESPONSE step=%s qr=%s input_type=%s ai_text='%s'", current_step, [q["label"] for q in quick_replies], input_type, ai_text[:80] if ai_text else "")

    return JSONResponse(content={
        "ai_response": ai_text,
        "quick_replies": quick_replies,
        "onboarding_phase": "collecting",
        "pet_id": None,
        "pet_card": None,
        "input_type": input_type,
        "collected": collected,
    })
