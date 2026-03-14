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

# Клички которые на 99% указывают на мужской пол
_MALE_NAMES = {
    "рекс", "барон", "граф", "тузик", "бобик", "шарик", "дружок",
    "мухтар", "полкан", "арчи", "боб", "бакс", "зевс", "марс",
    "гектор", "цезарь", "максимус", "брут", "рэй", "джек",
    "барсик", "тигр", "тигрик", "кузя", "васька", "мурзик",
    "рыжик", "пушок", "снежок", "лёва", "леопольд",
}

# Клички которые на 99% указывают на женский пол
_FEMALE_NAMES = {
    "мурка", "белка", "лада", "найда", "жучка", "дина", "ника",
    "альма", "пальма", "роза", "жасмин", "принцесса", "маркиза",
    "лейла", "багира", "симба", "муся", "кися", "пуся",
    "снежинка", "ромашка", "лапочка", "милашка",
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

def _build_system_prompt(collected: dict, step_instruction: str, current_step: str = "", quick_replies: list = None) -> str:
    today = date.today().strftime("%d %B %Y")
    iron_rules = (
        "\n\nЖЕЛЕЗНЫЕ ПРАВИЛА — нарушать нельзя никогда:\n"
        "1. Отвечай ТОЛЬКО на текущий шаг — смотри блок ТЕКУЩИЙ ШАГ.\n"
        "2. Никогда не задавай вопросы следующих шагов.\n"
        "3. Один вопрос за одно сообщение.\n"
        "4. Никаких emoji.\n"
        "5. Запрещённые слова: отлично, прекрасно, замечательно, зафиксировал, "
        "понял, конечно, разумеется, рад помочь, с чего начнём.\n"
        "6. Если есть блок КНОПКИ — текст должен вести именно к этим кнопкам.\n\n"
    )
    result = _CHARACTER_TEXT + "\n\n" + iron_rules + _PROMPT_TEMPLATE
    result = result.replace("{today_date}", today)
    result = result.replace("{step_instruction}", step_instruction)
    for key in _EMPTY_COLLECTED:
        val = collected.get(key)
        result = result.replace(f"{{{key}}}", str(val) if val is not None else "null")

    # Блок текущего шага и кнопок
    step_context = f"\n\nТЕКУЩИЙ ШАГ: {current_step}\n"
    if quick_replies:
        buttons_text = " | ".join([qr["label"] for qr in quick_replies])
        step_context += f"КНОПКИ КОТОРЫЕ УВИДИТ ПОЛЬЗОВАТЕЛЬ: [{buttons_text}]\n"
        step_context += "Напиши текст который естественно подводит к этим кнопкам.\n"
    else:
        step_context += "Кнопок нет — пользователь отвечает текстом.\n"
    step_context += (
        "ПРАВИЛО: пиши ТОЛЬКО про текущий шаг. "
        "Не упоминай следующие шаги. "
        "Один вопрос. Максимум 3 предложения если не указано иначе."
    )
    result += step_context
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
    if not collected.get("owner_name"):
        return "owner_name"

    if not collected.get("pet_name"):
        return "pet_name"

    # Угадывание вида из клички — сразу после pet_name, до goal
    if not collected.get("species") and not collected.get("_species_guessed"):
        name = (collected.get("pet_name") or "").lower().strip()
        if name in _DOG_NAMES:
            return "species_guess_dog"
        elif name in _CAT_NAMES:
            return "species_guess_cat"

    if not collected.get("goal"):
        return "goal"

    # Тревога — дать высказаться
    if collected.get("goal") == "Есть тревога" and not collected.get("_concern_heard"):
        return "concern"

    # Вид — если не определён после угадывания
    if not collected.get("species"):
        return "species"

    # Паспорт — обязательно между species и breed
    if not collected.get("breed") and not collected.get("_passport_skipped"):
        return "passport_offer"

    # Порода
    if not collected.get("breed"):
        if collected.get("_breed_category"):
            return "breed_subcategory"
        return "breed"

    # Дата / возраст
    if (not collected.get("birth_date") and
        not collected.get("age_years") and
        not collected.get("_age_skipped")):
        return "birth_date"

    # Пол
    if not collected.get("gender"):
        return "gender"

    # Кастрация
    if (collected.get("is_neutered") is None and
        not collected.get("_neutered_skipped")):
        return "is_neutered"

    # Аватар
    if (not collected.get("avatar_url") and
        not collected.get("_avatar_skipped")):
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
            'РАЗРЕШЕНО: поприветствуй и спроси имя пользователя.\n'
            'ЗАПРЕЩЕНО: упоминать ветеринарию, здоровье, функции приложения.\n'
            'МАКСИМУМ: 2 предложения.\n'
            'ПРИМЕР ТОЧНОГО ТЕКСТА: "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?"'
        ),

        "pet_name": (
            f'РАЗРЕШЕНО: поприветствуй {owner} и спроси кличку питомца.\n'
            f'ЗАПРЕЩЕНО: спрашивать вид, породу, возраст, цель.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР ТОЧНОГО ТЕКСТА: "Приятно, {owner}. Как зовут питомца?"'
        ),

        "species_guess_dog": (
            f'РАЗРЕШЕНО: уверенно предположить что {pet_name} — собака, спросить угадал ли.\n'
            f'ЗАПРЕЩЕНО: спрашивать цель, паспорт, породу, возраст.\n'
            f'ЗАПРЕЩЕНО: говорить "кто это такой" или задавать открытый вопрос о виде.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР ТОЧНОГО ТЕКСТА: "Ставлю на собаку — угадал?"'
        ),

        "species_guess_cat": (
            f'РАЗРЕШЕНО: уверенно предположить что {pet_name} — кошка, спросить угадал ли.\n'
            f'ЗАПРЕЩЕНО: спрашивать цель, паспорт, породу, возраст.\n'
            f'ЗАПРЕЩЕНО: говорить "кто это такой" или задавать открытый вопрос о виде.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР ТОЧНОГО ТЕКСТА: "Ставлю на кота — угадал?"'
        ),

        "goal": (
            f'РАЗРЕШЕНО: сказать что {pet_name} повезло и спросить чем помочь.\n'
            f'ЗАПРЕЩЕНО: спрашивать вид, породу, возраст, пол.\n'
            f'ЗАПРЕЩЕНО: упоминать что ты умеешь или что будет дальше.\n'
            f'МАКСИМУМ: 2 предложения.\n'
            f'ПРИМЕР ТОЧНОГО ТЕКСТА: "{pet_name} повезло — у него есть ты. Чем могу помочь?"'
        ),

        "concern": (
            f'РАЗРЕШЕНО: спросить что происходит с {pet_name}, дать высказаться полностью.\n'
            f'ЗАПРЕЩЕНО: задавать медицинские вопросы, ставить диагноз, пугать.\n'
            f'ЗАПРЕЩЕНО: торопить пользователя или переходить к следующим шагам.\n'
            f'МАКСИМУМ: 2 предложения.\n'
            f'ПРИМЕР ТОЧНОГО ТЕКСТА: "Расскажи. Что происходит с {pet_name}?"'
        ),

        "species": (
            f'{"РАЗРЕШЕНО: мягко сказать что работаешь только с кошками и собаками, спросить кошка или собака." if collected.get("_exotic_attempt") else "РАЗРЕШЕНО: спросить кошка или собака."}\n'
            f'{"ПРИМЕР: Пока работаю только с кошками и собаками. Кошка или собака есть?" if collected.get("_exotic_attempt") else "ПРИМЕР: Кошка или собака?"}\n'
            + (
                f'КОНТЕКСТ: пользователь только что рассказал о тревоге. '
                f'Скажи коротко что чтобы помочь — нужна пара вопросов. '
                f'Потом спроси кошка или собака.\n'
                f'ПРИМЕР: "Чтобы разобраться — нужна пара вопросов. Кошка или собака?"'
                if collected.get("_concern_heard") else ""
            )
            + f'\nЗАПРЕЩЕНО: спрашивать породу, возраст, пол.\n'
            f'МАКСИМУМ: 2 предложения.'
        ),

        "passport_offer": (
            f'КОНТЕКСТ: пользователь уже нажал Сфотографирую. Скажи что ждёшь фото. Одно предложение.\nПРИМЕР: "Жду фото — отправь прямо сюда."'
            if collected.get("_passport_photo_requested") else
            'РАЗРЕШЕНО: предложить сфотографировать ветпаспорт.\n'
            'ЗАПРЕЩЕНО: спрашивать породу, возраст, пол, вид.\n'
            'ЗАПРЕЩЕНО: упоминать что будет после паспорта.\n'
            'МАКСИМУМ: 2 предложения.\n'
            'ПРИМЕР ТОЧНОГО ТЕКСТА: "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу в карточку."'
        ),

        "breed": (
            'РАЗРЕШЕНО: попросить написать название породы. Одно предложение.\n'
            'ЗАПРЕЩЕНО: снова спрашивать о породе развёрнуто, предлагать фото.\n'
            'ПРИМЕР: "Напиши название — внесу в карточку."'
            if collected.get("_awaiting_breed_text")
            else
            f'РАЗРЕШЕНО: предложить сфотографировать для определения породы или выбрать Метис.\n'
            f'ЗАПРЕЩЕНО: спрашивать возраст, пол, дату рождения.\n'
            f'МАКСИМУМ: 2 предложения.\n'
            f'ПРИМЕР: "Сфотографируй — определю по фото. Или выбери Метис."'
            if collected.get("_breed_unknown")
            else
            f'РАЗРЕШЕНО: спросить название породы {pet_name}.\n'
            f'ЗАПРЕЩЕНО: предлагать сфотографировать сразу, спрашивать возраст или пол.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР ДЛЯ СОБАКИ: "Какая порода у {pet_name}? Если метис — тоже скажи."\n'
            f'ПРИМЕР ДЛЯ КОШКИ: "Какая порода у {pet_name}? Если беспородная — тоже скажи."'
        ),

        "breed_subcategory": (
            f'РАЗРЕШЕНО: уточнить подпороду — сказать что бывают разные варианты.\n'
            f'ЗАПРЕЩЕНО: спрашивать возраст, дату рождения, пол, кастрацию.\n'
            f'МАКСИМУМ: 1 предложение + список вариантов из кнопок.\n'
            f'ПРИМЕР: "Ретриверы бывают разные — уточни:"'
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
            (
                f'РАЗРЕШЕНО: сначала дай инсайт про породу {collected.get("breed", "")}, '
                f'потом спроси дату рождения.\n'
                f'ЗАПРЕЩЕНО: спрашивать пол, кастрацию, аватар.\n'
                f'МАКСИМУМ: 4 предложения (инсайт + вопрос о дате).\n'
                f'СТИЛЬ ИНСАЙТА: живо, как друг. Пример: "Лабрадоры едят за троих — вес их главная тема."\n'
                f'ПРИМЕР ВОПРОСА: "Когда родился {pet_name}? Если не знаешь точно — примерный возраст или пропустим."'
            )
            if collected.get("breed") and not collected.get("_breed_insight_shown")
            else
            (
                f'РАЗРЕШЕНО: спросить дату рождения или примерный возраст.\n'
                f'ЗАПРЕЩЕНО: спрашивать пол, кастрацию, аватар.\n'
                f'МАКСИМУМ: 2 предложения.\n'
                f'ПРИМЕР: "Когда родился {pet_name}? Если не знаешь — примерный возраст или пропустим."'
            )
        ),

        "gender": (
            f'РАЗРЕШЕНО: спросить пол {pet_name}.\n'
            f'ЗАПРЕЩЕНО: спрашивать кастрацию, аватар, что-либо ещё.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            + (
                f'КЛИЧКА ЯВНО МУЖСКАЯ. ПРИМЕР: "{pet_name} — мальчик?"'
                if (collected.get("pet_name") or "").lower() in _MALE_NAMES or
                   (collected.get("pet_name") or "").lower() in _DOG_NAMES
                else
                f'КЛИЧКА ЯВНО ЖЕНСКАЯ. ПРИМЕР: "{pet_name} — девочка?"'
                if (collected.get("pet_name") or "").lower() in _FEMALE_NAMES or
                   (collected.get("pet_name") or "").lower() in _CAT_NAMES
                else
                f'КЛИЧКА НЕЙТРАЛЬНАЯ. ПРИМЕР: "{pet_name} — мальчик или девочка?"'
            )
        ),

        "is_neutered": (
            f'РАЗРЕШЕНО: спросить {neutered_word} ли {pet_name}.\n'
            f'ЗАПРЕЩЕНО: спрашивать аватар, подводить итоги, упоминать следующие шаги.\n'
            f'МАКСИМУМ: 1 предложение.\n'
            f'ПРИМЕР: "{pet_name} {neutered_word}?"'
        ),

        "avatar": (
            f'РАЗРЕШЕНО: попросить фото для профиля {pet_name}.\n'
            f'ЗАПРЕЩЕНО: подводить итоги онбординга, говорить что карточка готова.\n'
            f'МАКСИМУМ: 2 предложения.\n'
            f'ПРИМЕР: "Последний штрих — фото для профиля. Можно сфотографировать или пропустить."'
        ),
    }

    return instructions.get(step, "Продолжи разговор естественно.")


def _detect_name_gender(pet_name: str, client) -> str:
    """Определяет вероятный пол по кличке через Gemini. Возвращает male/female/neutral."""
    if not pet_name or not client:
        return "neutral"

    prompt = (
        f'Кличка питомца: "{pet_name}"\n'
        f'Определи вероятный пол по этой кличке для русскоязычной аудитории.\n'
        f'Ответь ТОЛЬКО одним словом без пояснений: male, female, или neutral\n'
        f'Примеры:\n'
        f'"Рекс" → male\n'
        f'"Мурка" → female\n'
        f'"Иннокентий" → male\n'
        f'"Персефона" → female\n'
        f'"Снежана" → female\n'
        f'"Кнопка" → neutral\n'
        f'"Бублик" → neutral\n'
        f'"Архимед" → male\n'
        f'"Облако" → neutral'
    )

    try:
        temp_chat = client.chats.create(model="gemini-2.5-flash")
        response = temp_chat.send_message(prompt)
        result = (response.text or "").strip().lower()
        if result in ("male", "female", "neutral"):
            return result
        return "neutral"
    except Exception:
        return "neutral"


def _get_gender_quick_replies(pet_name: str, client=None) -> list:
    """Кнопки пола: уровень 1 — списки, уровень 2 — Gemini."""
    name_lower = (pet_name or "").lower().strip()

    # Уровень 1 — списки
    if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
        gender_hint = "male"
    elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
        gender_hint = "female"
    else:
        # Уровень 2 — Gemini
        gender_hint = _detect_name_gender(pet_name, client)

    if gender_hint == "male":
        return [
            {"label": "Да, мальчик", "value": "Да, мальчик", "preferred": True},
            {"label": "Нет, девочка", "value": "Нет, девочка", "preferred": False},
        ]
    elif gender_hint == "female":
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


def _get_step_quick_replies(step: str, collected: dict, client=None) -> list:
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

        "gender": _get_gender_quick_replies(pet, client),

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
        if msg_lower in ["да, пёс", "да", "пёс", "собака"]:
            updates["species"] = "dog"
            updates["_species_guessed"] = True
        elif msg_lower == "не угадал":
            updates["_species_guessed"] = True
            # species не записываем — пользователь сам выберет на шаге species
        else:
            # Любой другой ответ — считаем подтверждением
            updates["species"] = "dog"
            updates["_species_guessed"] = True

    elif step == "species_guess_cat":
        if msg_lower in ["кот"]:
            updates["species"] = "cat"
            updates["gender"] = "male"
            updates["_species_guessed"] = True
        elif msg_lower in ["кошка"]:
            updates["species"] = "cat"
            updates["gender"] = "female"
            updates["_species_guessed"] = True
        elif msg_lower == "не угадал":
            updates["_species_guessed"] = True
        else:
            # Любой другой ответ — считаем подтверждением (кот по умолчанию)
            updates["species"] = "cat"
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
        elif any(w in msg_lower for w in ["сфотографирую", "фото", "сфоткаю", "сниму"]):
            # Пользователь хочет сфотографировать — ставим флаг ожидания
            # _passport_skipped НЕ ставим — ждём OCR данные от фронта
            updates["_passport_photo_requested"] = True

    elif step == "breed":
        # 1. Кнопка "Знаю породу"
        if msg_lower == "знаю породу":
            updates["_awaiting_breed_text"] = True

        # 2. Кнопка "Не знаю породу" или "Метис / Не знаю"
        elif msg_lower in ["не знаю породу", "метис / не знаю"]:
            if collected.get("_breed_unknown"):
                # Второй раз — записываем Метис
                updates["breed"] = "Метис"
                updates.pop("_breed_unknown", None)
            else:
                # Первый раз — показать кнопки фото
                updates["_breed_unknown"] = True

        # 3. Кнопка фото — фронт открывает камеру, OCR обработается отдельно
        elif msg == "BREED_PHOTO":
            pass

        else:
            # 4. Пользователь написал название породы
            # 4a. Проверяем _BREED_CATEGORIES
            found_category = False
            for keyword, category in _BREED_CATEGORIES.items():
                if keyword in msg_lower:
                    updates["_breed_category"] = category
                    updates.pop("_awaiting_breed_text", None)
                    found_category = True
                    break

            if not found_category:
                # 4b. rapidfuzz
                match = fuzz_process.extractOne(msg, ALL_BREEDS, scorer=fuzz.WRatio, score_cutoff=80)
                if match:
                    breed_name = match[0]
                    breed_lower = breed_name.lower()
                    # Проверяем есть ли у найденной породы подкатегория
                    has_subcategory = False
                    for keyword, category in _BREED_CATEGORIES.items():
                        if keyword in breed_lower:
                            updates["_breed_category"] = category
                            has_subcategory = True
                            break
                    if not has_subcategory:
                        updates["breed"] = breed_name
                    updates.pop("_awaiting_breed_text", None)

                # 4c. Ничего не нашли — записываем как есть
                else:
                    updates["breed"] = msg.strip().capitalize()
                    updates.pop("_awaiting_breed_text", None)

    elif step == "breed_subcategory":
        if "другая" in msg_lower or "другой" in msg_lower:
            updates["_breed_category"] = "other"
        else:
            # Попробовать найти породу через rapidfuzz
            match = fuzz_process.extractOne(msg, ALL_BREEDS, scorer=fuzz.WRatio, score_cutoff=75)
            if match:
                updates["breed"] = match[0]
                updates.pop("_breed_category", None)
            else:
                # Записываем как есть — пользователь знает свою породу
                updates["breed"] = msg.strip().capitalize()
                updates.pop("_breed_category", None)

    elif step == "birth_date":
        # Всегда отмечаем что breed insight показан
        updates["_breed_insight_shown"] = True

        if msg_lower in ["знаю дату", "введу дату"]:
            updates["_wants_date_picker"] = True
        else:
            # При любом другом вводе — сбрасываем флаг DatePicker
            updates["_wants_date_picker"] = False

            if msg_lower in ["не знаю", "не знаю возраст", "пропустить"]:
                updates["_age_skipped"] = True
            elif msg_lower in ["примерный возраст", "полных лет"]:
                updates["_age_approximate"] = True
            else:
                parsed = _parse_age(msg) or _parse_age_with_gemini(msg, client)
                if parsed:
                    updates.update(parsed)
                    updates.pop("_age_approximate", None)

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
    quick_replies = override_quick_replies or _get_step_quick_replies(current_step, collected, client)

    # 8. Call Gemini — text only, no JSON
    try:
        history_rows = _load_chat_history(user_id, limit=20)
        gemini_history = []
        for row in history_rows:
            role = "model" if row["role"] == "ai" else "user"
            content = row.get("message") or ""
            if content:
                gemini_history.append({"role": role, "parts": [{"text": content}]})

        system_prompt = _build_system_prompt(collected, step_instruction, current_step, quick_replies)

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
