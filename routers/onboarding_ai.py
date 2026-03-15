# routers/onboarding_ai.py
# AI-driven onboarding v2.0 — backend controls steps, Gemini writes text only.

import json
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

    # Тревога — дать высказаться
    if collected.get("goal") == "Есть тревога" and not collected.get("_concern_heard"):
        return "concern"

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

    if step == "concern":
        return []

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
                for i, o in enumerate(opts[:4])
            ]
            qr.append({"label": "Другая порода", "value": "Другая порода", "preferred": False})
            return qr
        return [
            {"label": "Не знаю породу", "value": "Не знаю породу", "preferred": False},
        ]

    if step == "birth_date":
        if collected.get("_age_approximate"):
            return []
        return [
            {"label": "Знаю дату рождения", "value": "Знаю дату рождения", "preferred": True},
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
    """Return Gemini instruction for current step. Short and directive."""
    owner = collected.get("owner_name", "")
    pet = collected.get("pet_name", "")
    species = collected.get("species", "")
    breed = collected.get("breed", "")
    gender = collected.get("gender", "")
    hint = collected.get("_detected_gender_hint", "neutral")

    if step == "owner_name":
        return (
            "Спроси как зовут владельца. Это первое сообщение.\n"
            "ЗАПРЕЩЕНО: спрашивать что-то кроме имени, фраза 'С чего начнём'.\n"
            'ПРИМЕР: "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?"'
        )

    if step == "pet_name":
        return (
            f"Владельца зовут {owner}. Спроси кличку питомца.\n"
            f"Реакция на имя владельца встроена в вопрос — ОДНА фраза, не два предложения.\n"
            f"ЗАПРЕЩЕНО: 'Приятно познакомиться', отдельное приветствие, вопросы кроме клички.\n"
            f'ПРИМЕР: "{owner}, как зовут питомца?"'
        )

    if step == "species_guess_dog":
        return (
            f"Кличка {pet} похожа на собачью. Спроси подтверждение — собака?\n"
            f"ЗАПРЕЩЕНО: породу, возраст, пол, что-либо кроме подтверждения вида.\n"
            f'ПРИМЕР: "Ставлю на собаку — угадал?"'
        )

    if step == "species_guess_cat":
        return (
            f"Кличка {pet} похожа на кошачью. Спроси подтверждение — кот?\n"
            f"ЗАПРЕЩЕНО: породу, возраст, пол, что-либо кроме подтверждения вида.\n"
            f'ПРИМЕР: "Ставлю на кота — угадал?"'
        )

    if step == "goal":
        return (
            f"Спроси чем можешь помочь с {pet}.\n"
            f"Кличку в дательном падеже: {pet} -> {pet}у (если мужской тип окончания).\n"
            f"НЕ использовать 'у него' / 'у неё' — пол неизвестен.\n"
            f"ЗАПРЕЩЕНО: вид, порода, возраст, пол, фраза 'С чего начнём'.\n"
            f'ПРИМЕР: "{pet} повезло — ты рядом. Чем могу помочь?"'
        )

    if step == "concern":
        return (
            f"Пользователя что-то беспокоит в {pet}. Спроси что происходит.\n"
            f"Дай высказаться. Не предлагай решений.\n"
            f"ЗАПРЕЩЕНО: уточняющие вопросы, предложения, советы, вид/порода/возраст.\n"
            f'ПРИМЕР: "Расскажи. Что происходит с {pet}?"'
        )

    if step == "species":
        if collected.get("_exotic_attempt"):
            return (
                f"Пользователь назвал экзотическое животное. Мы работаем только с кошками и собаками.\n"
                f'ПРИМЕР: "Пока работаю только с кошками и собаками. Кошка или собака есть?"'
            )
        if collected.get("_concern_heard"):
            return (
                f"Пользователь рассказал о тревоге. Теперь тебе нужно узнать — кошка или собака.\n"
                f'ПРИМЕР: "Чтобы разобраться — нужна пара вопросов. Кошка или собака?"'
            )
        return (
            'Спроси вид питомца: кошка или собака.\n'
            'ЗАПРЕЩЕНО: порода, возраст, пол.\n'
            'ПРИМЕР: "Кошка или собака?"'
        )

    if step == "passport_offer":
        return (
            f"Предложи сфотографировать ветпаспорт {pet}. Скажи что сам перенесёшь данные.\n"
            f"ЗАПРЕЩЕНО: порода, возраст, пол, кастрация.\n"
            f'ПРИМЕР: "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу в карточку."'
        )

    if step == "breed":
        if collected.get("_breed_unknown"):
            return (
                f"Пользователь не знает породу {pet}. Предложи загрузить фото или пропустить.\n"
                f'ПРИМЕР: "Загрузи фото {pet} — определю породу сам. Или пропускаем."'
            )
        if collected.get("_breed_photo_requested"):
            return (
                f"Ждём фото {pet} для определения породы.\n"
                f'ПРИМЕР: "Жду фото — отправь прямо сюда."'
            )
        if collected.get("_breed_clarification_options"):
            opts = ", ".join(collected["_breed_clarification_options"])
            return (
                f"Нужно уточнить породу. Варианты: {opts}.\n"
                f"Спроси какой вариант правильный.\n"
                f'ПРИМЕР: "Уточни — какая именно?"'
            )
        species_label = "собаки" if species == "dog" else "кошки"
        metis = "Если метис — тоже скажи." if species == "dog" else "Если беспородная — тоже скажи."
        return (
            f"Спроси породу {species_label}. {metis}\n"
            f"ЗАПРЕЩЕНО: возраст, пол, кастрация, дата рождения.\n"
            f'ПРИМЕР: "Какая порода у {pet}? {metis}"'
        )

    if step == "birth_date":
        insight = ""
        if breed:
            insight = f"Начни с ОДНОГО короткого интересного факта о породе {breed}. Потом спроси дату.\n"
        if collected.get("_age_approximate"):
            return (
                f"Пользователь хочет указать примерный возраст {pet} текстом.\n"
                f"Спроси сколько лет или месяцев.\n"
                f'ПРИМЕР: "Сколько примерно лет {pet}?"'
            )
        return (
            f"{insight}Спроси когда родился {pet}.\n"
            f"ЗАПРЕЩЕНО: пол, кастрация, порода.\n"
            f'ПРИМЕР: "Когда родился {pet}?"'
        )

    if step == "gender":
        if hint == "male":
            return (
                f"Кличка {pet} похожа на мужскую. Спроси — мальчик?\n"
                f"ЗАПРЕЩЕНО: кастрация, возраст, порода.\n"
                f'ПРИМЕР: "{pet} — мальчик?"'
            )
        if hint == "female":
            return (
                f"Кличка {pet} похожа на женскую. Спроси — девочка?\n"
                f"ЗАПРЕЩЕНО: кастрация, возраст, порода.\n"
                f'ПРИМЕР: "{pet} — девочка?"'
            )
        return (
            f"Спроси пол {pet} — мальчик или девочка.\n"
            f"ЗАПРЕЩЕНО: кастрация, возраст, порода.\n"
            f'ПРИМЕР: "{pet} — мальчик или девочка?"'
        )

    if step == "is_neutered":
        word = "стерилизована" if gender == "female" else "кастрирован"
        return (
            f"Спроси {word} ли {pet}.\n"
            f"ЗАПРЕЩЕНО: любые другие вопросы кроме кастрации/стерилизации.\n"
            f'ПРИМЕР: "{pet} {word}?"'
        )

    if step == "avatar":
        return (
            f"Попроси фото {pet} для профиля. Это последний шаг.\n"
            f"ЗАПРЕЩЕНО: любые другие вопросы.\n"
            f'ПРИМЕР: "И последнее — фото {pet}. Мордашка для профиля."'
        )

    return "Ответь пользователю коротко."


# ── System prompt ──────────────────────────────────────────────────────────────

def _build_system_prompt(
    collected: dict,
    step_instruction: str,
    current_step: str = "",
    quick_replies: list = None,
) -> str:
    """Build system prompt: character + known + rules + instruction + buttons."""

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

    # --- Контекстные заметки ---
    ctx = []
    if collected.get("_concern_heard"):
        ctx.append("Пользователь рассказал о тревоге — в финале вернись к ней.")
    if collected.get("_breed_unknown"):
        ctx.append("Пользователь не знает породу.")
    ctx_block = ("\nКОНТЕКСТ:\n" + "\n".join(f"  - {c}" for c in ctx) + "\n") if ctx else ""

    # --- Кнопки ---
    if quick_replies:
        labels = " | ".join(qr["label"] for qr in quick_replies)
        btn = (f"\nКНОПКИ КОТОРЫЕ УВИДИТ ПОЛЬЗОВАТЕЛЬ: [{labels}]\n"
               f"Пиши текст который ВЕДЁТ именно к этим кнопкам. "
               f"Не перечисляй варианты в тексте — пользователь увидит кнопки сам.")
    else:
        btn = "\nКнопок нет — пользователь отвечает текстом."

    # --- Сборка ---
    return (
        f"{_CHARACTER_TEXT.strip()}\n"
        f"\n---\n"
        f"\nУЖЕ ИЗВЕСТНО О ПОЛЬЗОВАТЕЛЕ:\n{known_block}\n"
        f"{ctx_block}"
        f"\n=== ЖЕЛЕЗНЫЕ ПРАВИЛА ===\n"
        f"1. Отвечай ТОЛЬКО на задачу ниже — ничего другого\n"
        f"2. ОДИН вопрос за сообщение\n"
        f"3. НОЛЬ emoji\n"
        f"4. Максимум 2 предложения\n"
        f"5. ЗАПРЕЩЁННЫЕ СЛОВА — никогда не произноси: "
        f"Понял, Отлично, Прекрасно, Замечательно, Зафиксировал, "
        f"Конечно, Разумеется, Рад помочь, С чего начнём, Хорошо, "
        f"Приятно познакомиться, Давай начнём\n"
        f"6. ЗАПРЕЩЕНО упоминать имя Dominik в тексте вместо клички питомца\n"
        f"=========================\n"
        f"\nТВОЯ ЗАДАЧА СЕЙЧАС:\n{step_instruction}"
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
    """Fallback text if Gemini returns empty response."""
    pet = collected.get("pet_name", "питомец")
    fallbacks = {
        "owner_name": "Как тебя зовут?",
        "pet_name": "Как зовут питомца?",
        "species_guess_dog": "Собака?",
        "species_guess_cat": "Кот?",
        "goal": f"Чем могу помочь с {pet}?",
        "concern": f"Расскажи что беспокоит в {pet}.",
        "species": "Кошка или собака?",
        "passport_offer": "Есть ветпаспорт? Могу сфотографировать и перенести данные.",
        "breed": f"Какая порода у {pet}?",
        "birth_date": f"Когда родился {pet}?",
        "gender": f"{pet} — мальчик или девочка?",
        "is_neutered": f"{pet} кастрирован?",
        "avatar": f"Загрузи фото {pet} для профиля.",
    }
    return fallbacks.get(step, f"Расскажи мне про {pet}.")


# ── User input parser ─────────────────────────────────────────────────────────

def _parse_user_input(msg: str, step: str, collected: dict, client=None) -> dict:
    """Parse user message and return field updates for collected dict."""
    if not msg or not msg.strip():
        return {}

    raw = msg.strip()
    low = raw.lower()
    clean = low.rstrip(".,!?;:\u2026")
    updates: dict = {}

    if step == "owner_name":
        if any(w in low for w in ["не скажу", "аноним", "не хочу", "не твоё дело"]):
            updates["owner_name"] = "Друг"
            return updates
        result = _parse_name(raw, "owner_name")
        if result.get("is_valid") and result.get("name"):
            updates["owner_name"] = result["name"]
        elif result.get("needs_ai") and client:
            ai = _parse_name_with_gemini(raw, "owner_name", client)
            if ai.get("is_valid") and ai.get("name"):
                updates["owner_name"] = ai["name"]

    elif step == "pet_name":
        if any(w in low for w in ["не знаю", "нет имени", "без имени", "пока нет"]):
            updates["pet_name"] = "Питомец"
            return updates
        result = _parse_name(raw, "pet_name")
        if result.get("is_valid") and result.get("name"):
            updates["pet_name"] = result["name"]
        elif result.get("needs_ai") and client:
            ai = _parse_name_with_gemini(raw, "pet_name", client)
            if ai.get("is_valid") and ai.get("name"):
                updates["pet_name"] = ai["name"]

    elif step == "species_guess_dog":
        if any(w in clean for w in ["да", "пёс", "пес", "собака", "угадал"]):
            updates["species"] = "dog"
        else:
            updates["_species_guessed"] = True

    elif step == "species_guess_cat":
        if clean in ("кот", "да кот", "да, кот"):
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif clean in ("кошка", "да кошка", "да, кошка"):
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif "кошка" in clean:
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif "кот" in clean.split():
            updates["species"] = "cat"
            updates["gender"] = "male"
        else:
            updates["_species_guessed"] = True

    elif step == "goal":
        goal_map = {
            "слежу за здоровьем": "Слежу за здоровьем",
            "прививки и плановое": "Прививки и плановое",
            "веду дневник": "Веду дневник",
            "кое-что беспокоит": "Есть тревога",
            "кое что беспокоит": "Есть тревога",
            "беспокоит": "Есть тревога",
            "тревога": "Есть тревога",
            "здоровь": "Слежу за здоровьем",
            "привив": "Прививки и плановое",
            "дневник": "Веду дневник",
        }
        for key, value in goal_map.items():
            if key in low:
                updates["goal"] = value
                break
        if not updates.get("goal") and len(raw) > 2:
            updates["goal"] = raw

    elif step == "concern":
        updates["_concern_heard"] = True

    elif step == "species":
        if clean == "кот" or (clean.split() and clean.split()[0] == "кот"):
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif "кошка" in clean:
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif any(w in clean for w in ["собака", "пёс", "пес"]):
            updates["species"] = "dog"
        else:
            exotic = [
                "попугай", "хомяк", "рыбка", "черепаха", "кролик",
                "крыса", "морская свинка", "хорёк", "хорек",
                "ящерица", "змея", "шиншилла", "птица", "канарейка",
            ]
            if any(w in low for w in exotic):
                updates["_exotic_attempt"] = True

    elif step == "passport_offer":
        if "сфотографирую" in low or clean == "сфотографирую":
            updates["_passport_photo_requested"] = True
        elif any(w in low for w in ["вручную", "паспорта нет", "нет паспорта", "лучше вручную"]):
            updates["_passport_skipped"] = True
        elif any(w in low for w in ["нет", "пропуст", "без паспорта"]):
            updates["_passport_skipped"] = True

    elif step == "breed":
        if any(w in low for w in ["не знаю породу", "не знаю", "хз", "без понятия"]):
            updates["_breed_unknown"] = True
        elif clean in ("пропустить", "пропуск", "скип"):
            updates["breed"] = "Метис"
        elif raw == "BREED_PHOTO":
            updates["_breed_photo_requested"] = True
        elif "другая порода" in low:
            updates["_breed_clarification_options"] = None
            updates["_breed_unknown"] = None
        elif low in ("дворняга", "дворняжка", "метис", "беспородная", "беспородный",
                      "дворняга или метис", "двортерьер"):
            updates["breed"] = "Метис"
        else:
            best_match = None
            best_score = 0
            for breed_name in ALL_BREEDS:
                score = fuzz.ratio(low, breed_name.lower())
                if score > best_score:
                    best_score = score
                    best_match = breed_name
            if best_score >= 80 and best_match:
                updates["breed"] = best_match
            elif client:
                result = _parse_breed_with_gemini(raw, collected.get("species", "dog"), client)
                if result.get("breed"):
                    updates["breed"] = result["breed"]
                elif result.get("needs_clarification") and result.get("options"):
                    updates["_breed_clarification_options"] = result["options"]

    elif step == "birth_date":
        if clean in ("знаю дату рождения", "знаю дату"):
            updates["_wants_date_picker"] = True
        elif clean in ("примерный возраст", "примерно"):
            updates["_age_approximate"] = True
            updates["_wants_date_picker"] = False
        elif clean in ("не знаю", "хз", "без понятия"):
            updates["_age_skipped"] = True
            updates["_wants_date_picker"] = False
        else:
            updates["_wants_date_picker"] = False
            updates["_age_approximate"] = False
            age_result = _parse_age(raw)
            if age_result.get("parsed"):
                if age_result.get("age_years") is not None:
                    updates["age_years"] = age_result["age_years"]
                if age_result.get("birth_date"):
                    updates["birth_date"] = age_result["birth_date"]
            elif client:
                age_result = _parse_age_with_gemini(raw, client)
                if age_result.get("age_years") is not None:
                    updates["age_years"] = age_result["age_years"]
                elif age_result.get("birth_date"):
                    updates["birth_date"] = age_result["birth_date"]

    elif step == "gender":
        if any(w in clean for w in ["мальчик", "кобель", "самец", "пацан", "парень"]):
            updates["gender"] = "male"
        elif any(w in clean for w in ["девочка", "сука", "самка"]):
            updates["gender"] = "female"
        elif clean in ("да", "ага", "верно", "точно", "угу"):
            hint = collected.get("_detected_gender_hint", "neutral")
            if hint == "male":
                updates["gender"] = "male"
            elif hint == "female":
                updates["gender"] = "female"
        elif clean == "нет":
            hint = collected.get("_detected_gender_hint", "neutral")
            if hint == "male":
                updates["gender"] = "female"
            elif hint == "female":
                updates["gender"] = "male"

    elif step == "is_neutered":
        if clean in ("да", "ага", "угу", "кастрирован", "стерилизована", "кастрирована"):
            updates["is_neutered"] = True
        elif clean in ("нет", "не", "нет ещё", "нет еще"):
            updates["is_neutered"] = False

    elif step == "avatar":
        if raw == "AVATAR_PHOTO":
            pass
        elif any(w in low for w in ["пропустить", "пропуск", "потом", "позже", "не сейчас", "скип"]):
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

    # 6. Second _get_current_step — after parsing
    current_step = _get_current_step(collected)

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

            pet_card = _build_pet_card(collected, pet_id, short_id)
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

    # 11. Compute quick replies (once)
    quick_replies = _get_step_quick_replies(current_step, collected, client)

    # 12. Compute step instruction
    step_instruction = _get_step_instruction(current_step, collected)

    # 13. Build system prompt
    system_prompt = _build_system_prompt(
        collected, step_instruction, current_step, quick_replies
    )

    # 14. Call Gemini — text only, no JSON
    try:
        history_rows = _load_chat_history(user_id, limit=20)
        gemini_history = []
        for row in history_rows:
            role = "model" if row["role"] == "ai" else "user"
            content = row.get("message") or ""
            if content:
                gemini_history.append({"role": role, "parts": [{"text": content}]})

        chat = client.chats.create(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
            history=gemini_history,
        )
        response = chat.send_message(actual_message or "Начни онбординг")
        ai_text = (response.text or "").strip()
        ai_text = _remove_stop_phrases(ai_text)
    except Exception as e:
        logger.error("[gemini_call] %s", e)
        ai_text = "Что-то пошло не так. Попробуй ещё раз."

    # 15. Fallback if empty response
    if not ai_text:
        ai_text = _get_fallback_text(current_step, collected)

    # 16. Save AI response
    _save_ai_message(user_id, ai_text, None, user_chat_id)

    # 17. Return response
    input_type = "date_picker" if (current_step == "birth_date" and collected.get("_wants_date_picker")) else "text"

    return JSONResponse(content={
        "ai_response": ai_text,
        "quick_replies": quick_replies,
        "onboarding_phase": "collecting",
        "pet_id": None,
        "pet_card": None,
        "input_type": input_type,
        "collected": collected,
    })
