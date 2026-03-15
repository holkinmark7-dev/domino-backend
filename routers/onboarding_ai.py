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
from rapidfuzz import process as fuzz_process, fuzz
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
    if not collected.get("owner_name"):
        return "owner_name"

    if not collected.get("pet_name"):
        return "pet_name"

    # Угадывание вида из кличек — ТОЛЬКО для явных животных кличек
    if not collected.get("species") and not collected.get("_species_guessed"):
        name = (collected.get("pet_name") or "").lower().strip()
        if name in _DOG_NAMES:
            return "species_guess_dog"
        elif name in _CAT_NAMES:
            return "species_guess_cat"

    if not collected.get("goal"):
        return "goal"

    if collected.get("goal") == "Есть тревога" and not collected.get("_concern_heard"):
        return "concern"

    if not collected.get("species"):
        return "species"

    if not collected.get("_passport_skipped"):
        return "passport_offer"

    # Breed — один шаг, без subcategory
    if not collected.get("breed"):
        return "breed"

    if (not collected.get("birth_date") and
        not collected.get("age_years") and
        not collected.get("_age_skipped")):
        return "birth_date"

    # Gender пропускается если species=cat (пол уже известен из Кот/Кошка)
    if not collected.get("gender") and collected.get("species") != "cat":
        return "gender"

    if (collected.get("is_neutered") is None and
        not collected.get("_neutered_skipped")):
        return "is_neutered"

    if (not collected.get("avatar_url") and
        not collected.get("_avatar_skipped")):
        return "avatar"

    return "complete"


def _get_step_quick_replies(step: str, collected: dict, client=None) -> list:
    """Return quick reply buttons for a specific step. Backend-controlled, not Gemini."""
    pet = collected.get("pet_name") or ""

    # Определяем gender hint для кнопок gender
    if step == "gender" and not collected.get("_detected_gender_hint"):
        name_lower = pet.lower()
        if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
            collected["_detected_gender_hint"] = "male"
        elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
            collected["_detected_gender_hint"] = "female"
        else:
            collected["_detected_gender_hint"] = _detect_name_gender(pet, client)

    hint = collected.get("_detected_gender_hint", "neutral")

    qr_map = {
        "owner_name": [],
        "pet_name": [],

        "species_guess_dog": [
            {"label": "Да, пёс", "value": "Да, пёс", "preferred": True},
            {"label": "Не угадал", "value": "Не угадал", "preferred": False},
        ],

        "species_guess_cat": [
            {"label": "Кот", "value": "Кот",
             "preferred": pet.lower() not in _FEMALE_CAT_NAMES},
            {"label": "Кошка", "value": "Кошка",
             "preferred": pet.lower() in _FEMALE_CAT_NAMES},
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
            {"label": "Лучше вручную", "value": "Лучше вручную", "preferred": False},
            {"label": "Паспорта нет", "value": "Паспорта нет", "preferred": False},
        ],

        "breed": (
            # Ждём фото — кнопок нет
            []
            if collected.get("_breed_photo_requested")
            # Не знает породу — фото или пропустить
            else [
                {"label": "Загрузить фото", "value": "BREED_PHOTO", "preferred": True},
                {"label": "Пропустить", "value": "Пропустить породу", "preferred": False},
            ]
            if collected.get("_breed_unknown")
            # Ждём уточнения от Gemini — динамические кнопки
            else [
                {"label": opt, "value": opt, "preferred": False}
                for opt in collected.get("_breed_clarification_options", [])
            ] + [{"label": "Другой вариант", "value": "Другой вариант", "preferred": False}]
            if collected.get("_breed_clarification_options")
            # Первый показ — только "Не знаю"
            else [
                {"label": "Не знаю породу", "value": "Не знаю породу", "preferred": False},
            ]
        ),

        "birth_date": (
            [{"label": "Не знаю", "value": "Не знаю возраст", "preferred": False}]
            if collected.get("_age_approximate")
            else [
                {"label": "Знаю дату рождения", "value": "Знаю дату рождения", "preferred": True},
                {"label": "Примерный возраст", "value": "Примерный возраст", "preferred": False},
                {"label": "Не знаю", "value": "Не знаю возраст", "preferred": False},
            ]
        ),

        "gender": (
            [
                {"label": "Да, мальчик", "value": "Да, мальчик", "preferred": True},
                {"label": "Нет, девочка", "value": "Нет, девочка", "preferred": False},
            ] if hint == "male" else
            [
                {"label": "Да, девочка", "value": "Да, девочка", "preferred": True},
                {"label": "Нет, мальчик", "value": "Нет, мальчик", "preferred": False},
            ] if hint == "female" else
            [
                {"label": "Мальчик", "value": "Мальчик", "preferred": False},
                {"label": "Девочка", "value": "Девочка", "preferred": False},
            ]
        ),

        "is_neutered": [
            {"label": "Да", "value": "Да", "preferred": False},
            {"label": "Нет", "value": "Нет", "preferred": False},
        ],

        "avatar": [
            {"label": "Загрузить фото", "value": "AVATAR_PHOTO", "preferred": True},
            {"label": "Пропустить", "value": "Пропустить", "preferred": False},
        ],
    }

    return qr_map.get(step, [])


def _get_step_instruction(step: str, collected: dict) -> str:
    """Return Gemini instruction for a specific step."""
    owner = collected.get("owner_name") or "хозяин"
    pet_name = collected.get("pet_name") or "питомец"
    species = collected.get("species") or ""
    gender = collected.get("gender") or ""
    hint = collected.get("_detected_gender_hint", "neutral")

    neutered_word = (
        "стерилизована"
        if (species in ("cat", "кошка") and gender == "female") or
           (species == "dog" and gender == "female")
        else "кастрирован"
    )

    instructions = {
        "owner_name": (
            'РАЗРЕШЕНО: поприветствуй тепло, скажи что ты Dominik, спроси имя.\n'
            'ЗАПРЕЩЕНО: упоминать ветеринарию, здоровье, функции приложения.\n'
            'МАКСИМУМ: 2 предложения.\n'
            'EDGE CASE: если пользователь написал отказ ("не скажу") -> прими без вопросов.\n'
            'EDGE CASE: если цифры/символы -> "Не расслышал — как тебя зовут?"\n'
            'ПРИМЕР: "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?"'
        ),

        "pet_name": (
            f'РАЗРЕШЕНО: отреагировать на имя {owner} одной живой фразой и спросить кличку.\n'
            f'ЗАПРЕЩЕНО: "приятно познакомиться", хвалить имя, два предложения.\n'
            f'ЗАПРЕЩЕНО: спрашивать вид, породу, возраст, цель.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРАВИЛО: реакция встроена в вопрос — не отдельным предложением.\n'
            f'EDGE CASE: "не знаю" -> "Без имени пока — можно добавить позже."\n'
            f'EDGE CASE: явно не кличка -> "Не расслышал кличку — как зовут питомца?"\n'
            f'ПРИМЕРЫ:\n'
            f'  owner="{owner}" -> "{owner} — и кто же у тебя живёт?"\n'
            f'  "{owner}, как зовут питомца?"\n'
            f'  "{owner}, кто у тебя?"'
        ),

        "species_guess_dog": (
            f'РАЗРЕШЕНО: уверенно предположить что {pet_name} — собака, спросить угадал ли.\n'
            f'ЗАПРЕЩЕНО: "кто это такой", открытый вопрос о виде, следующие шаги.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР: "Ставлю на собаку — угадал?"'
        ),

        "species_guess_cat": (
            f'РАЗРЕШЕНО: уверенно предположить что {pet_name} — кошка, спросить угадал ли.\n'
            f'ЗАПРЕЩЕНО: "кто это такой", открытый вопрос о виде, следующие шаги.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР: "Ставлю на кота — угадал?"'
        ),

        "goal": (
            f'РАЗРЕШЕНО: отреагировать на кличку {pet_name} тепло, спросить чем помочь.\n'
            f'ЗАПРЕЩЕНО: "у него", "у неё" — пол неизвестен. ЗАПРЕЩЕНО: порода, возраст.\n'
            f'МАКСИМУМ: 2 предложения.\n'
            f'ПРАВИЛО: кличка в дательном падеже (Рексу, Мурке, Кузе, Себастьяну).\n'
            f'ПРИМЕРЫ:\n'
            f'  "{pet_name} повезло — ты рядом. Чем могу помочь?"\n'
            f'  "{pet_name} повезло с хозяином. Чем могу помочь?"'
        ),

        "concern": (
            f'РАЗРЕШЕНО: спросить что происходит с {pet_name} в творительном падеже.\n'
            f'ЗАПРЕЩЕНО: медицинские вопросы, диагноз, торопить, следующие шаги.\n'
            f'МАКСИМУМ: 2 предложения.\n'
            f'ПРИМЕР: "Расскажи. Что происходит с {pet_name}?"'
        ),

        "species": (
            f'РАЗРЕШЕНО: мягко объяснить что работаешь только с кошками и собаками.\n'
            f'ПРИМЕР: "Пока работаю только с кошками и собаками. Кошка или собака есть?"'
            if collected.get("_exotic_attempt") else
            f'РАЗРЕШЕНО: сказать что чтобы помочь — нужна пара вопросов. Спросить кошка или собака.\n'
            f'ПРИМЕР: "Чтобы разобраться — нужна пара вопросов. Кошка или собака?"'
            if collected.get("_concern_heard") else
            'РАЗРЕШЕНО: спросить кошка или собака. Одно предложение.\n'
            'ПРИМЕР: "Кошка или собака?"'
        ),

        "passport_offer": (
            f'РАЗРЕШЕНО: сказать что ждёшь фото паспорта.\n'
            f'ЗАПРЕЩЕНО: спрашивать про породу или что-либо ещё.\n'
            f'ПРИМЕР: "Жду фото — отправь прямо сюда."'
            if collected.get("_passport_photo_requested") else
            'РАЗРЕШЕНО: предложить сфотографировать ветпаспорт.\n'
            'ЗАПРЕЩЕНО: спрашивать породу, возраст, пол.\n'
            'МАКСИМУМ: 2 предложения.\n'
            'ПРИМЕР: "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу в карточку."'
        ),

        "breed": (
            'РАЗРЕШЕНО: сказать что ждёшь фото питомца.\n'
            'ПРИМЕР: "Жду фото — отправь прямо сюда."'
            if collected.get("_breed_photo_requested") else

            f'РАЗРЕШЕНО: предложить сфотографировать {pet_name} для определения породы.\n'
            f'ЗАПРЕЩЕНО: сразу называть Метисом.\n'
            f'ПРИМЕР: "Загрузи фото {pet_name} — определю породу сам. Или пропускаем."'
            if collected.get("_breed_unknown") else

            f'РАЗРЕШЕНО: уточнить какой именно вариант из предложенных.\n'
            f'ЗАПРЕЩЕНО: спрашивать возраст, пол, дату.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР: "Уточни — какой именно?"'
            if collected.get("_breed_clarification_options") else

            f'РАЗРЕШЕНО: спросить породу {pet_name}.\n'
            f'ЗАПРЕЩЕНО: предлагать фото сразу, спрашивать возраст или пол.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР СОБАКА: "Какая порода у {pet_name}? Если метис — тоже скажи."\n'
            f'ПРИМЕР КОШКА: "Какая порода у {pet_name}? Если беспородная — тоже скажи."'
        ),

        "birth_date": (
            # Первый раз — с инсайтом о породе
            f'РАЗРЕШЕНО: дать 1-2 живых предложения про породу {collected.get("breed", "")}, '
            f'потом спросить дату рождения {pet_name}.\n'
            f'ЗАПРЕЩЕНО: упоминать прививки, медицину, пол, кастрацию.\n'
            f'МАКСИМУМ: 3 предложения суммарно.\n'
            f'ПРАВИЛО: кличка в родительном падеже.\n'
            f'РЕАКЦИЯ НА ДАТУ — вычисли возраст и отреагируй:\n'
            f'  до 6 мес -> "Совсем малыш — только начинается."\n'
            f'  6-12 мес -> "Семь месяцев — самый живой возраст."\n'
            f'  1-3 года -> "Полтора года — в самом расцвете сил."\n'
            f'  3-7 лет -> "Четыре года — лучший возраст."\n'
            f'  7-10 лет -> "Семь лет — взрослый, знает чего хочет."\n'
            f'  10+ лет -> "Десять лет — опыт и мудрость."\n'
            f'EDGE CASE: дата в будущем -> "Это дата в будущем — может, ошибся годом?"\n'
            f'EDGE CASE: 50+ лет назад -> "Что-то дата выглядит необычно — всё верно?"\n'
            f'ПРИМЕР: "Лабрадоры едят за троих. Когда родился {pet_name}?"'
            if collected.get("breed") and not collected.get("_breed_insight_shown")
            else
            f'РАЗРЕШЕНО: спросить дату рождения {pet_name}.\n'
            f'ЗАПРЕЩЕНО: упоминать прививки, медицину.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРАВИЛО: кличка в родительном падеже.\n'
            f'РЕАКЦИЯ НА ДАТУ — вычисли возраст и отреагируй живо (см. таблицу выше).\n'
            f'EDGE CASE: дата в будущем -> "Это дата в будущем — может, ошибся годом?"\n'
            f'EDGE CASE: 50+ лет назад -> "Что-то дата выглядит необычно — всё верно?"\n'
            f'ПРИМЕР: "Когда родился {pet_name}?"'
        ),

        "gender": (
            f'ТЕКУЩАЯ КЛИЧКА ПИТОМЦА: {pet_name}\n'
            f'ЗАПРЕЩЕНО: использовать слово "Dominik" вместо клички.\n'
            f'ЗАПРЕЩЕНО: спрашивать кастрацию, аватар.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            + (
                f'КЛИЧКА ЯВНО МУЖСКАЯ.\n'
                f'ПРИМЕР: "{pet_name} — мальчик?"'
                if hint == "male" else
                f'КЛИЧКА ЯВНО ЖЕНСКАЯ.\n'
                f'ПРИМЕР: "{pet_name} — девочка?"'
                if hint == "female" else
                f'КЛИЧКА НЕЙТРАЛЬНАЯ.\n'
                f'ПРИМЕР: "{pet_name} — мальчик или девочка?"'
            )
        ),

        "is_neutered": (
            f'РАЗРЕШЕНО: спросить {neutered_word} ли {pet_name}.\n'
            f'ЗАПРЕЩЕНО: аватар, итоги, следующие шаги.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР: "{pet_name} {neutered_word}?"'
        ),

        "avatar": (
            f'РАЗРЕШЕНО: попросить фото {pet_name} для профиля. Это последний шаг.\n'
            f'ЗАПРЕЩЕНО: говорить "сфотографируй" — кнопка называется "Загрузить фото".\n'
            f'ЗАПРЕЩЕНО: подводить итоги, говорить что карточка готова.\n'
            f'МАКСИМУМ: 2 предложения.\n'
            f'ПРАВИЛО: кличка в родительном падеже.\n'
            f'ПРИМЕР: "И последнее — фото {pet_name}. Мордашка для профиля."\n'
            f'ПРИМЕР: "Последний штрих — загрузи фото {pet_name}. Или пропусти, добавишь позже."'
        ),
    }

    return instructions.get(step, "Продолжи разговор естественно.")


# ── System prompt ──────────────────────────────────────────────────────────────

def _build_system_prompt(
    collected: dict,
    step_instruction: str,
    current_step: str = "",
    quick_replies: list = None
) -> str:
    today = date.today().strftime("%d %B %Y")

    # Только заполненные поля — не передаём null
    field_labels = {
        "owner_name": "Владелец",
        "pet_name": "Кличка",
        "species": "Вид",
        "breed": "Порода",
        "birth_date": "Дата рождения",
        "age_years": "Возраст (лет)",
        "gender": "Пол",
        "is_neutered": "Кастрирован",
        "goal": "Цель",
    }
    known_lines = []
    for key, label in field_labels.items():
        val = collected.get(key)
        if val is not None and val != "" and val != "null":
            known_lines.append(f"{label}: {val}")

    known_fields = "\n".join(known_lines) if known_lines else "пока ничего не известно"

    # Контекст для Gemini — внутренние флаги
    context_notes = []
    if collected.get("_breed_unknown"):
        context_notes.append("Пользователь не знает породу.")
    if collected.get("_concern_heard"):
        context_notes.append("Пользователь рассказал о тревоге — в финале вернись к ней.")
    if collected.get("_breed_clarification_options"):
        opts = ", ".join(collected["_breed_clarification_options"])
        context_notes.append(f"Предложены варианты породы: {opts}")

    # Кнопки которые увидит пользователь
    if quick_replies:
        labels = " | ".join(qr["label"] for qr in quick_replies)
        buttons_line = f"\nКНОПКИ: [{labels}]\nПиши текст который ведёт именно к этим кнопкам."
    else:
        buttons_line = "\nКнопок нет — пользователь отвечает текстом."

    # Склонение клички
    pet_name = collected.get("pet_name", "")
    declension = f"\nСклоняй кличку '{pet_name}' правильно по-русски." if pet_name else ""

    # Собираем промпт
    result = _CHARACTER_TEXT.strip()
    result += "\n\n---\n"
    result += f"Сегодня: {today}\n"
    result += f"\nУЖЕ ИЗВЕСТНО:\n{known_fields}\n"

    if context_notes:
        result += "\nКОНТЕКСТ:\n" + "\n".join(f"- {n}" for n in context_notes) + "\n"

    result += f"\nТВОЯ ЗАДАЧА СЕЙЧАС:\n{step_instruction}"
    result += buttons_line
    result += declension
    result += "\n\nМАКСИМУМ 3 предложения. Один вопрос."

    return result


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
    pet = collected.get("pet_name", "питомца")
    fallbacks = {
        "owner_name": "Привет. Как тебя зовут?",
        "pet_name": "Как зовут питомца?",
        "species_guess_dog": "Ставлю на собаку — угадал?",
        "species_guess_cat": "Ставлю на кота — угадал?",
        "goal": "Чем могу помочь?",
        "concern": "Расскажи — что происходит?",
        "species": "Кошка или собака?",
        "passport_offer": "Если есть ветпаспорт — сфотографируй.",
        "breed": f"Какая порода у {pet}?",
        "birth_date": f"Когда родился {pet}?",
        "gender": "Мальчик или девочка?",
        "is_neutered": "Кастрирован?",
        "avatar": f"Добавим фото {pet}?",
    }
    return fallbacks.get(step, "Расскажи подробнее.")


# ── User input parser ─────────────────────────────────────────────────────────

def _parse_user_input(
    msg: str, step: str, collected: dict, client=None
) -> dict:
    """Парсит сообщение. Возвращает только изменения для collected."""
    updates = {}
    msg_lower = msg.lower().strip()

    if step == "owner_name":
        result = _parse_name(msg, "owner_name")
        if not result["is_valid"] and (result.get("needs_ai") or len(msg) > 10):
            result = _parse_name_with_gemini(msg, "owner_name", client)
        if result.get("is_valid") and result.get("name"):
            updates["owner_name"] = result["name"]
            updates.pop("_name_invalid_attempt", None)
        elif msg_lower in ("не скажу", "аноним", "анонимно", "-", "\u2014"):
            updates["owner_name"] = "Хозяин"
        else:
            updates["_name_invalid_attempt"] = True

    elif step == "pet_name":
        result = _parse_name(msg, "pet_name")
        if not result["is_valid"] and (result.get("needs_ai") or len(msg) > 10):
            result = _parse_name_with_gemini(msg, "pet_name", client)
        if result.get("is_valid") and result.get("name"):
            updates["pet_name"] = result["name"]
            updates.pop("_name_invalid_attempt", None)
        elif msg_lower in ("не знаю", "без имени", "пока без имени"):
            updates["pet_name"] = "Питомец"
        else:
            updates["_name_invalid_attempt"] = True

    elif step == "species_guess_dog":
        if msg_lower in ("да, пёс", "да", "пёс", "собака", "он собака"):
            updates["species"] = "dog"
            updates["_species_guessed"] = True
        elif msg_lower == "не угадал":
            updates["_species_guessed"] = True

    elif step == "species_guess_cat":
        if msg_lower in ("кот", "он кот"):
            updates["species"] = "cat"
            updates["gender"] = "male"
            updates["_species_guessed"] = True
        elif msg_lower in ("кошка", "она кошка"):
            updates["species"] = "cat"
            updates["gender"] = "female"
            updates["_species_guessed"] = True
        elif msg_lower == "не угадал":
            updates["_species_guessed"] = True

    elif step == "goal":
        if "беспокоит" in msg_lower or "тревог" in msg_lower:
            updates["goal"] = "Есть тревога"
        elif "здоровь" in msg_lower or "слежу" in msg_lower:
            updates["goal"] = "Слежу за здоровьем"
        elif "привив" in msg_lower or "планов" in msg_lower:
            updates["goal"] = "Прививки и плановое"
        elif "дневник" in msg_lower or "веду" in msg_lower:
            updates["goal"] = "Веду дневник"
        else:
            updates["goal"] = msg.strip()

    elif step == "concern":
        updates["_concern_heard"] = True

    elif step == "species":
        if msg_lower in ("кот", "кот у меня"):
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif msg_lower in ("кошка", "кошка у меня"):
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif msg_lower in ("собака", "собака у меня", "пёс"):
            updates["species"] = "dog"
        else:
            exotic = ["попугай", "хомяк", "черепах", "рыб", "кролик",
                      "крыс", "морск", "змея", "ящериц", "птиц", "хорёк"]
            if any(w in msg_lower for w in exotic):
                updates["_exotic_attempt"] = True

    elif step == "passport_offer":
        if any(w in msg_lower for w in ["сфотографирую", "фото", "сниму"]):
            updates["_passport_photo_requested"] = True
        elif any(w in msg_lower for w in ["вручную", "сам", "нет", "паспорта нет", "лучше вручную"]):
            updates["_passport_skipped"] = True

    elif step == "breed":
        if msg_lower == "не знаю породу":
            updates["_breed_unknown"] = True

        elif msg == "BREED_PHOTO":
            updates["_breed_photo_requested"] = True

        elif msg_lower == "пропустить породу":
            updates["breed"] = "Метис"
            updates.pop("_breed_unknown", None)

        elif msg_lower == "другой вариант":
            # Пользователь хочет другой вариант — сбрасываем и ждём ввода
            updates["_breed_clarification_options"] = None

        elif collected.get("_breed_clarification_options"):
            # Пользователь выбрал один из предложенных вариантов
            options = collected.get("_breed_clarification_options", [])
            matched = False
            for opt in options:
                if msg_lower == opt.lower():
                    updates["breed"] = opt
                    updates["_breed_clarification_options"] = None
                    updates.pop("_breed_unknown", None)
                    matched = True
                    break
            if not matched:
                # Не выбрал из списка — записываем как ввёл
                updates["breed"] = msg.strip().capitalize()
                updates["_breed_clarification_options"] = None

        else:
            # Пользователь написал название породы — парсим
            # Уровень 1: rapidfuzz 80%
            match = fuzz_process.extractOne(
                msg, ALL_BREEDS, scorer=fuzz.WRatio, score_cutoff=80
            )
            if match:
                updates["breed"] = match[0]
                updates.pop("_breed_unknown", None)
            else:
                # Уровень 2: Gemini
                species = collected.get("species", "dog")
                result = _parse_breed_with_gemini(msg, species, client)
                if result.get("needs_clarification") and result.get("options"):
                    updates["_breed_clarification_options"] = result["options"]
                elif result.get("breed"):
                    updates["breed"] = result["breed"]
                    updates.pop("_breed_unknown", None)
                else:
                    updates["breed"] = msg.strip().capitalize()
                    updates.pop("_breed_unknown", None)

    elif step == "birth_date":
        updates["_breed_insight_shown"] = True

        if msg_lower in ("знаю дату рождения", "знаю дату"):
            updates["_wants_date_picker"] = True
        else:
            updates["_wants_date_picker"] = False

            if msg_lower in ("не знаю", "не знаю возраст", "пропустить"):
                updates["_age_skipped"] = True
            elif msg_lower in ("примерный возраст", "примерно"):
                updates["_age_approximate"] = True
            else:
                result = _parse_age(msg)
                if not result["parsed"]:
                    result = _parse_age_with_gemini(msg, client)
                if result.get("age_years") is not None:
                    updates["age_years"] = result["age_years"]
                    updates.pop("_age_approximate", None)
                elif result.get("birth_date"):
                    updates["birth_date"] = result["birth_date"]
                    updates.pop("_wants_date_picker", None)

    elif step == "gender":
        if any(w in msg_lower for w in ["мальчик", "самец", "кобель", "пёс"]):
            updates["gender"] = "male"
        elif any(w in msg_lower for w in ["девочка", "самка", "сука"]):
            updates["gender"] = "female"
        elif msg_lower.rstrip(".,!") == "да":
            hint = collected.get("_detected_gender_hint", "neutral")
            updates["gender"] = "male" if hint != "female" else "female"

    elif step == "is_neutered":
        msg_clean = msg.strip().rstrip(".,!?;:").lower()
        if msg_clean in {"да", "yes", "кастрирован", "стерилизована", "стерилизован"}:
            updates["is_neutered"] = True
        elif msg_clean in {"нет", "no", "не кастрирован", "не стерилизована"}:
            updates["is_neutered"] = False

    elif step == "avatar":
        if "пропуст" in msg_lower:
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
    input_type = "date_picker" if collected.get("_wants_date_picker") else "text"

    return JSONResponse(content={
        "ai_response": ai_text,
        "quick_replies": quick_replies,
        "onboarding_phase": "collecting",
        "pet_id": None,
        "pet_card": None,
        "input_type": input_type,
        "collected": collected,
    })
