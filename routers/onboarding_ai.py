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
from routers.services.breeds import BREED_EN
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


# ── Step logic (backend-controlled) ─────────────────────────────────────────

def _get_current_step(collected: dict) -> str:
    """Determine current step based on collected data."""
    if not collected.get("owner_name"):
        return "owner_name"
    if not collected.get("pet_name"):
        return "pet_name"
    if not collected.get("goal"):
        return "goal"
    if not collected.get("species"):
        return "species"
    if not collected.get("breed"):
        if collected.get("_passport_skipped") or collected.get("birth_date"):
            return "breed"
        return "passport_offer"
    if not collected.get("birth_date") and not collected.get("age_years"):
        return "birth_date"
    if not collected.get("gender"):
        return "gender"
    if collected.get("is_neutered") is None:
        return "is_neutered"
    if not collected.get("avatar_url") and not collected.get("_avatar_skipped"):
        return "avatar"
    return "complete"


def _get_step_instruction(step: str, collected: dict) -> str:
    """Return Gemini instruction for a specific step."""
    pet = collected.get("pet_name") or "питомец"
    owner = collected.get("owner_name") or ""
    species = collected.get("species") or ""
    gender = collected.get("gender") or ""

    instructions = {
        "owner_name":
            'Поприветствуй тепло и спроси имя пользователя. '
            'Пример: "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?"',

        "pet_name":
            f'Поприветствуй {owner} и спроси кличку питомца. '
            f'Пример: "Приятно, {owner}. Как зовут твоего питомца?"',

        "goal":
            f'Скажи что {pet} повезло что у него есть хозяин. '
            f'Спроси чем можешь помочь. '
            f'Пример: "{pet}у повезло — у него есть ты. Чем могу помочь?"',

        "species":
            'Спроси кошка или собака. '
            'Пример: "Кошка или собака?"',

        "passport_offer":
            f'Предложи сфотографировать ветпаспорт {pet}а. '
            f'Объясни что сам перенесёшь все данные. '
            f'Пример: "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу в карточку."',

        "breed":
            f'Спроси породу {pet}а. Если собака — упомяни что метис тоже хорошо. '
            f'Если кошка — что беспородная тоже хорошо.',

        "birth_date":
            f'Объясни зачем нужна дата рождения (для точного расчёта прививок). '
            f'Спроси когда родился {pet}.',

        "gender":
            f'Спроси пол {pet}а. Если имя явно мужское — уточни "мальчик?". '
            f'Если женское — "девочка?". Если непонятно — спроси прямо.',

        "is_neutered":
            f'Спроси кастрирован ли {pet}. '
            f'Используй правильную форму: кот→кастрирован, кошка→стерилизована, '
            f'пёс→кастрирован, собака→стерилизована.',

        "avatar":
            f'Попроси фото {pet}а для профиля. Скажи что это последний штрих. '
            f'Пример: "Последний штрих — фото {pet}а. Мордашка для профиля."',
    }
    return instructions.get(step, "Продолжи разговор.")


def _get_gender_quick_replies(pet_name: str) -> list:
    """Determine gender buttons based on pet name heuristic."""
    male_names = {"рекс", "шарик", "бобик", "тузик", "бублик", "марс", "зевс", "барон"}
    female_names = {"мурка", "белка", "рыжик", "ласка", "роза", "луна", "зара"}
    name_lower = (pet_name or "").lower()

    if name_lower in male_names:
        return [
            {"label": "Да, мальчик", "value": "Да", "preferred": True},
            {"label": "Нет, девочка", "value": "Нет, девочка", "preferred": False},
        ]
    elif name_lower in female_names:
        return [
            {"label": "Да, девочка", "value": "Да", "preferred": True},
            {"label": "Нет, мальчик", "value": "Нет, мальчик", "preferred": False},
        ]
    else:
        return [
            {"label": "Мальчик", "value": "Мальчик", "preferred": False},
            {"label": "Девочка", "value": "Девочка", "preferred": False},
        ]


def _get_step_quick_replies(step: str, collected: dict) -> list:
    """Return quick reply buttons for a specific step. Backend-controlled, not Gemini."""
    pet = collected.get("pet_name") or ""

    qr = {
        "owner_name": [],

        "pet_name": [],

        "goal": [
            {"label": "Слежу за здоровьем", "value": "Слежу за здоровьем", "preferred": False},
            {"label": "Прививки и плановое", "value": "Прививки и плановое", "preferred": False},
            {"label": "Веду дневник", "value": "Веду дневник", "preferred": False},
            {"label": "Кое-что беспокоит", "value": "Кое-что беспокоит", "preferred": False},
        ],

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

        "breed": [
            {"label": "Сфотографировать", "value": "BREED_PHOTO", "preferred": True},
            {"label": "Знаю породу", "value": "Знаю породу", "preferred": False},
            {"label": "Не знаю породу", "value": "Не знаю породу", "preferred": False},
        ],

        "birth_date": [],

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
    return qr.get(step, [])


# ── User input parser (no Gemini) ───────────────────────────────────────────

def _parse_user_input(message: str, step: str, collected: dict) -> dict:
    """Extract data from user message without Gemini. Returns dict with updated fields."""
    msg = message.strip().lower()
    updates = {}

    if step == "owner_name":
        updates["owner_name"] = message.strip()

    elif step == "pet_name":
        updates["pet_name"] = message.strip()

    elif step == "goal":
        goal_map = {
            "слежу за здоровьем": "Слежу за здоровьем",
            "прививки и плановое": "Прививки и плановое",
            "веду дневник": "Веду дневник",
            "кое-что беспокоит": "Есть тревога",
        }
        for key, val in goal_map.items():
            if key in msg:
                updates["goal"] = val
                break
        if not updates:
            updates["goal"] = message.strip()

    elif step == "species":
        if "кот" in msg and "кошка" not in msg:
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif "кошка" in msg:
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif "собака" in msg or "пёс" in msg or "пес" in msg:
            updates["species"] = "dog"

    elif step == "passport_offer":
        if any(w in msg for w in ["заполню", "сам", "нет", "паспорта нет"]):
            updates["_passport_skipped"] = True

    elif step == "breed":
        if msg not in ["знаю породу", "не знаю породу", "breed_photo"]:
            if "не знаю" in msg or "метис" in msg or "дворняга" in msg or "беспородн" in msg:
                updates["breed"] = "Метис"
            else:
                updates["breed"] = message.strip()

    elif step == "birth_date":
        # Format DD.MM.YYYY or DD/MM/YYYY
        match = re.search(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', message)
        if match:
            d, m, y = match.groups()
            updates["birth_date"] = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
        elif "не знаю" in msg or "незнаю" in msg:
            pass  # backend will ask for approximate age
        else:
            # Try to find age in years
            age_match = re.search(r'(\d+)\s*(лет|год|года)', msg)
            if age_match:
                updates["age_years"] = float(age_match.group(1))
            # Try months
            month_match = re.search(r'(\d+)\s*(месяц|мес)', msg)
            if month_match:
                updates["age_years"] = round(float(month_match.group(1)) / 12, 1)

    elif step == "gender":
        if any(w in msg for w in ["мальчик", "самец", "male"]):
            updates["gender"] = "male"
        elif any(w in msg for w in ["девочка", "самка", "female"]):
            updates["gender"] = "female"
        elif msg == "да" and collected.get("gender"):
            pass  # confirm existing guess — gender already set
        elif msg == "да":
            updates["gender"] = "male"  # default confirm

    elif step == "is_neutered":
        if msg in {"да", "yes", "кастрирован", "стерилизована", "стерилизован"}:
            updates["is_neutered"] = True
        elif msg in {"нет", "no"}:
            updates["is_neutered"] = False

    elif step == "avatar":
        if "пропуст" in msg:
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
            "onboarding_stage": "complete",
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
    pet = collected.get("pet_name") or "питомец"
    goal = (collected.get("goal") or "").lower()

    if "тревог" in goal or "беспокоит" in goal:
        return f"Карточка готова. Теперь расскажи — что тебя беспокоит?"
    elif "прививк" in goal or "плановое" in goal:
        return f"Профиль {pet} создан. Загляни — там уже основное. Остальное внесём вместе."
    elif "дневник" in goal:
        return f"Карточка {pet} готова. Открой профиль и дополни что знаешь, или просто пиши мне."
    else:
        return f"Профиль {pet} готов. Дополнить можно в любой момент — сам или через меня."


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
                collected["breed"] = top["name_ru"]
                if color:
                    collected["color"] = color
                actual_message = f"По фото определил: {top['name_ru']} ({int(top['probability'] * 100)}%)."
            else:
                override_quick_replies = [
                    {"label": f"{b['name_ru']} ({int(b['probability'] * 100)}%)",
                     "value": b["name_ru"],
                     "preferred": i == 0}
                    for i, b in enumerate(breeds[:3])
                ]
                options = ", ".join([f"{b['name_ru']} {int(b['probability'] * 100)}%" for b in breeds[:3]])
                actual_message = f"Вижу несколько вариантов: {options}. Какой подходит?"

    # 2c. Avatar URL from message text
    elif message_text and message_text.startswith("avatar_url:"):
        avatar_url = message_text[len("avatar_url:"):]
        if avatar_url:
            collected["avatar_url"] = avatar_url
        actual_message = "Фото загружено."

    # 3. Parse user input (text messages only, not special inputs)
    current_step = _get_current_step(collected)

    if actual_message and actual_message == message_text:
        updates = _parse_user_input(actual_message, current_step, collected)
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
        api_key = os.environ.get("GEMINI_API_KEY", "")
        client = genai.Client(api_key=api_key)

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

    # 9. Save AI response
    _save_ai_message(user_id, ai_text, None, user_chat_id)

    # 10. Return response
    return JSONResponse(content={
        "ai_response": ai_text,
        "quick_replies": quick_replies,
        "onboarding_phase": "collecting",
        "pet_id": None,
        "pet_card": None,
        "input_type": "date" if current_step == "birth_date" else "text",
        "collected": collected,
    })
