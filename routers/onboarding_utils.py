# routers/onboarding_utils.py
# Utility functions for AI-driven onboarding.

import re
import os
import json
import logging
from datetime import date, datetime

import openai

from routers.onboarding_constants import _CHARACTER_TEXT

logger = logging.getLogger(__name__)


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
    """Parse age from text. Returns age_years as float (1.5 = полтора года)."""
    text = msg.lower().strip()

    # Специальные случаи
    if "полтора" in text:
        if "месяц" in text:
            return {"age_years": 0.125, "birth_date": None, "parsed": True}  # 1.5 мес
        return {"age_years": 1.5, "birth_date": None, "parsed": True}  # 1.5 года
    if "полгода" in text or "пол года" in text:
        return {"age_years": 0.5, "birth_date": None, "parsed": True}

    year_match = re.search(r'(\d+)\s*(лет|год|года)', text)
    month_match = re.search(r'(\d+)\s*(месяц|месяца|месяцев)', text)

    years = 0
    months = 0
    has_data = False

    if year_match:
        years = int(year_match.group(1))
        has_data = True
    if month_match:
        months = int(month_match.group(1))
        has_data = True

    if has_data:
        # Комбинированный: "2 года 3 месяца" → 2.25
        total = years + round(months / 12, 2)
        return {"age_years": total, "birth_date": None, "parsed": True}

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


def _validate_input_with_ai(text: str, field: str, collected: dict) -> dict:
    """
    AI проверяет ввод пользователя. Возвращает:
    {"valid": True, "value": "Марк"} — если это валидное значение
    {"valid": False, "hint": "Напиши своё имя — одно слово"} — если мусор
    """
    pet = collected.get("pet_name", "питомец")
    owner = collected.get("owner_name", "")

    prompts = {
        "owner_name": (
            f'Пользователь проходит регистрацию. Его попросили назвать своё имя.\n'
            f'Он написал: "{text}"\n\n'
            f'ПРАВИЛА:\n'
            f'1. Если это имя — верни JSON: {{"valid": true, "value": "Имя"}}\n'
            f'2. Извлекай имя из ЛЮБОЙ фразы:\n'
            f'   "Марк" → Марк\n'
            f'   "меня зовут Аня" → Аня\n'
            f'   "Холкин Марк Викторович" → Марк\n'
            f'   "привет я Дима" → Дима\n'
            f'   "слушай, меня Саша зовут, у меня собака болеет" → Саша\n'
            f'3. Если НЕ имя (приветствие без имени, мат, вопрос, бред, цифры, ссылка) — '
            f'верни JSON: {{"valid": false, "hint": "подсказка"}}\n'
            f'   "привет" → {{"valid": false, "hint": "Как мне к тебе обращаться?"}}\n'
            f'   "блять" → {{"valid": false, "hint": "Напиши своё имя — просто одно слово"}}\n'
            f'   "123" → {{"valid": false, "hint": "Как тебя зовут?"}}\n'
            f'   "что это" → {{"valid": false, "hint": "Мне нужно твоё имя — как обращаться?"}}\n'
            f'   "Йо" → {{"valid": false, "hint": "Как мне к тебе обращаться?"}}\n'
            f'   "Ку" → {{"valid": false, "hint": "Как тебя зовут?"}}\n'
            f'   "Старт" → {{"valid": false, "hint": "Напиши своё имя"}}\n'
            f'   "Го" → {{"valid": false, "hint": "Как тебя зовут?"}}\n'
            f'ВАЖНО: слова из 1-2 букв (Ку, Йо, Го, Ну) — это НЕ имена. Команды (Старт, Start, Меню, Помощь) — тоже НЕ имена.\n'
            f'ОТВЕТ — только JSON, ничего больше.'
        ),
        "pet_name": (
            f'Пользователь проходит регистрацию питомца. Его попросили назвать кличку.\n'
            f'Он написал: "{text}"\n\n'
            f'ПРАВИЛА:\n'
            f'1. Если это кличка — верни JSON: {{"valid": true, "value": "Кличка"}}\n'
            f'2. ЛЮБАЯ кличка допустима — и обычные (Рекс, Мурка) и человеческие (Борис, Маша, Степан, Филипп)\n'
            f'3. Извлекай кличку из ЛЮБОЙ фразы:\n'
            f'   "Бобик" → Бобик\n'
            f'   "его зовут Борис" → Борис\n'
            f'   "питомца зовут Доминик" → Доминик\n'
            f'   "кличка Рекс" → Рекс\n'
            f'   "ну собаку Шариком назвали" → Шарик\n'
            f'   "Степан" → Степан\n'
            f'4. Если НЕ кличка (мат, бред, вопрос, команда, "собака" без клички) — '
            f'верни JSON: {{"valid": false, "hint": "подсказка"}}\n'
            f'   "привет" → {{"valid": false, "hint": "Как зовут питомца?"}}\n'
            f'   "собака" → {{"valid": false, "hint": "А как зовут? Кличка"}}\n'
            f'   "не понимаю" → {{"valid": false, "hint": "Просто напиши кличку питомца"}}\n'
            f'ОТВЕТ — только JSON, ничего больше.'
        ),
    }

    prompt = prompts.get(field)
    if not prompt:
        return {"valid": False, "hint": ""}

    try:
        oai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        response = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.0,
        )
        raw_response = (response.choices[0].message.content or "").strip()
        # Убрать markdown обёртку если есть
        raw_response = raw_response.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw_response)
        return result
    except Exception as e:
        logger.error("[validate_ai] %s", e)
        return {"valid": False, "hint": ""}


def _check_breed_subtypes(breed_name: str, species: str = "dog") -> dict:
    """
    AI проверяет: порода точная или группа с подвидами?
    Возвращает:
      {"exact": True, "breed": "Мопс"} — записать как есть
      {"exact": False, "options": ["Сибирский хаски", "Аляскинский хаски"]} — нужно уточнение
    """
    species_label = "собак" if species == "dog" else "кошек"

    prompt = (
        f'Порода {species_label}: "{breed_name}"\n\n'
        f'ВАЖНО: Это должна быть РЕАЛЬНАЯ порода домашнего животного ({species_label}).\n'
        f'Если это НЕ порода (фантазия, дикое животное, предмет, бред) — верни:\n'
        f'{{"exact": true, "breed": "{breed_name}"}}\n'
        f'НЕ придумывай подвиды для несуществующих пород.\n\n'
        f'Вопрос: это ТОЧНОЕ название одной конкретной породы, '
        f'или это ОБЩЕЕ/СОКРАЩЁННОЕ название группы пород с подвидами?\n\n'
        f'ПРАВИЛА:\n'
        f'1. Если точная порода (Мопс, Бигль, Акита-ину, Мейн-кун, Бенгальская) — верни:\n'
        f'   {{"exact": true, "breed": "Полное официальное название"}}\n'
        f'2. Если группа/сокращение с подвидами — верни список подвидов (2-6 штук):\n'
        f'   {{"exact": false, "options": ["Подвид 1", "Подвид 2", "Подвид 3"]}}\n'
        f'3. Исправь опечатки в названии если есть\n\n'
        f'Примеры:\n'
        f'"Мопс" → {{"exact": true, "breed": "Мопс"}}\n'
        f'"Хаски" → {{"exact": false, "options": ["Сибирский хаски", "Аляскинский хаски", "Аляскинский маламут"]}}\n'
        f'"Овчарка" → {{"exact": false, "options": ["Немецкая овчарка", "Бельгийская малинуа", "Кавказская овчарка", "Среднеазиатская овчарка"]}}\n'
        f'"Лабрадор" → {{"exact": true, "breed": "Лабрадор-ретривер"}}\n'
        f'"Корги" → {{"exact": true, "breed": "Вельш-корги пемброк"}}\n'
        f'"Британская" → {{"exact": false, "options": ["Британская короткошёрстная", "Британская длинношёрстная"]}}\n'
        f'"Сфинкс" → {{"exact": false, "options": ["Канадский сфинкс", "Донской сфинкс", "Петерболд"]}}\n'
        f'"Бигль" → {{"exact": true, "breed": "Бигль"}}\n'
        f'"Шпиц" → {{"exact": false, "options": ["Померанский шпиц", "Немецкий шпиц", "Японский шпиц"]}}\n'
        f'"Такса" → {{"exact": false, "options": ["Стандартная такса", "Миниатюрная такса", "Кроличья такса"]}}\n\n'
        f'ОТВЕТ — только JSON, ничего больше.'
    )

    try:
        oai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        response = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        raw_response = (response.choices[0].message.content or "").strip()
        raw_response = raw_response.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw_response)
        logger.info("[ONB] breed subtypes: '%s' → %s", breed_name, result)
        return result
    except Exception as e:
        logger.error("[ONB] breed subtypes error: %s", e)
        # При ошибке — записать как есть
        return {"exact": True, "breed": breed_name}


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

    # --- Hint если пользователь ввёл мусор ---
    hint = collected.get("_input_hint", "")
    hint_block = f"\nПОЛЬЗОВАТЕЛЬ НАПИСАЛ НЕ ТО. Мягко направь: {hint}\n" if hint else ""

    # --- Сборка ---
    return (
        f"{_CHARACTER_TEXT.strip()}\n"
        f"\n---\n"
        f"\nУЖЕ ИЗВЕСТНО:\n{known_block}\n"
        f"{ctx_block}"
        f"{decl}"
        f"{hint_block}"
        f"\n=== ЖЕЛЕЗНЫЕ ПРАВИЛА ===\n"
        f"1. Скажи РОВНО тот текст который указан в задаче — не добавляй слова\n"
        f"2. ОДИН вопрос, ОДНО-ДВА предложения максимум\n"
        f"3. НОЛЬ emoji\n"
        f"4. НИКОГДА не произноси: Понял, Отлично, Прекрасно, Замечательно, "
        f"Зафиксировал, Конечно, Разумеется, Рад помочь, С чего начнём, "
        f"Хорошо, Приятно познакомиться, Давай начнём\n"
        f"5. НЕ используй имя Dominik вместо клички питомца\n"
        f"6. Если пользователь написал не по теме — мягко переспроси. "
        f"Не ругай, не объясняй что это онбординг. Примеры переспроса:\n"
        f'   - для имени: "Как мне к тебе обращаться?"\n'
        f'   - для клички: "Как зовут питомца?"\n'
        f'   - для вида: "Кошка или собака?"\n'
        f'   - для остального: просто повтори текущий вопрос другими словами\n'
        f"7. Разделяй логические части ответа двойным переносом строки (\\n\\n).\n"
        f'   Реакция на ответ + новый вопрос = два абзаца. Пример: "Рекс — сильное имя!\\n\\nКакой он породы?"\n'
        f"   Один факт или один вопрос = один абзац, не разделяй.\n"
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
        r'^Запомнил[,\.]?\s*',
        r'^Записал[,\.]?\s*',
        r'^Принял[,\.]?\s*',
        r'^Супер[,\.]?\s*',
        r'^Круто[,\.]?\s*',
        r'^Здорово[,\.]?\s*',
        r'^Класс[,\.]?\s*',
        r'^Так[,\.]?\s*',
        r'^Ок[,\.]?\s*',
        r'^Разумеется[,\.]?\s*',
    ]
    for pattern in stop_starts:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
    return text
