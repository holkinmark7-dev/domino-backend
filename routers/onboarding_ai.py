# routers/onboarding_ai.py
# AI-driven onboarding via Gemini. Replaces FSM-based onboarding_new.py.

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
from routers.services.memory import get_user_flags, update_user_flags

logger = logging.getLogger(__name__)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── System prompt ──────────────────────────────────────────────────────────────

_PROMPT_PATH = Path(__file__).parent.parent / "design-reference" / "onboarding-prompt.txt"
try:
    _PROMPT_TEMPLATE: str = _PROMPT_PATH.read_text(encoding="utf-8")
except FileNotFoundError:
    raise RuntimeError(f"[onboarding_ai] Промпт не найден: {_PROMPT_PATH}")

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
}


def _build_system_prompt(collected: dict) -> str:
    today = date.today().strftime("%d %B %Y")
    prompt = _PROMPT_TEMPLATE.replace("{today_date}", today)
    for key in _EMPTY_COLLECTED:
        val = collected.get(key)
        prompt = prompt.replace(f"{{{key}}}", str(val) if val is not None else "null")
    return prompt


def _parse_gemini_json(raw: str) -> dict:
    """Extract and parse JSON from Gemini response (handles markdown fences)."""
    cleaned = re.sub(r"```json|```", "", raw).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        return json.loads(cleaned[start : end + 1])
    return json.loads(cleaned)


def _merge_collected(existing: dict, new_fields: dict) -> dict:
    """Merge new collected fields into existing. Non-null new values overwrite."""
    merged = dict(existing)
    for key, val in new_fields.items():
        if val is not None and val != "null":
            merged[key] = val
    return merged


def _is_complete(collected: dict) -> bool:
    """Check if all required fields plus at least one age field are filled."""
    required_ok = all(collected.get(f) for f in _REQUIRED_FIELDS)
    age_ok = any(collected.get(f) for f in _AGE_FIELDS)
    return required_ok and age_ok


def _create_pet(user_id: str, collected: dict) -> str | None:
    """Create pet in supabase from collected data. Returns pet_id or None."""
    try:
        species_raw = (collected.get("species") or "").lower()
        if "cat" in species_raw or "кош" in species_raw or "кот" in species_raw:
            species = "cat"
        else:
            species = "dog"

        gender_raw = (collected.get("gender") or "").lower()
        if any(w in gender_raw for w in ["female", "female", "девочк", "самка", "женск"]):
            gender = "female"
        elif any(w in gender_raw for w in ["male", "мальчик", "самец", "мужск"]):
            gender = "male"
        else:
            gender = None

        neutered_raw = str(collected.get("is_neutered") or "").lower()
        is_neutered = neutered_raw in {"да", "yes", "true", "1", "кастрирован", "стерилизован", "стерилизована"}

        birth_date = collected.get("birth_date")
        if birth_date:
            # Normalise common formats: DD.MM.YYYY → YYYY-MM-DD
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


def handle_onboarding_ai(
    user_id: str,
    message_text: str,
    passport_ocr_data: dict | None = None,
) -> JSONResponse:
    """
    Handle one turn of AI-driven onboarding.
    Returns JSONResponse with the same schema as regular /chat responses.
    """
    # 1. Load accumulated collected data from user flags
    user_flags = get_user_flags(user_id)
    collected: dict = dict(_EMPTY_COLLECTED)
    collected.update(user_flags.get("onboarding_collected") or {})

    # 2. Handle passport OCR data (inject into collected if successful)
    actual_message = message_text
    if passport_ocr_data and passport_ocr_data.get("success") and passport_ocr_data.get("confidence", 0) >= 0.6:
        ocr = passport_ocr_data
        if ocr.get("pet_name") and not collected.get("pet_name"):
            collected["pet_name"] = ocr["pet_name"]
        if ocr.get("breed") and not collected.get("breed"):
            collected["breed"] = ocr["breed"]
        if ocr.get("birth_date") and not collected.get("birth_date"):
            collected["birth_date"] = ocr["birth_date"]
        if ocr.get("gender") and not collected.get("gender"):
            collected["gender"] = ocr["gender"]
        actual_message = "__passport_ocr_applied__"
    elif passport_ocr_data and not (passport_ocr_data.get("success") and passport_ocr_data.get("confidence", 0) >= 0.6):
        actual_message = "__passport_ocr_failed__"

    # 3. Save user message (skip empty WELCOME ping)
    user_chat_id = None
    if actual_message and actual_message.strip():
        user_chat_id = _save_user_message(user_id, actual_message)

    # 4. Load chat history for context
    history_rows = _load_chat_history(user_id, limit=30)

    # 5. Build Gemini history (role: "user"/"model")
    gemini_history: list[dict] = []
    for row in history_rows:
        role = "model" if row["role"] == "ai" else "user"
        content = row.get("message") or ""
        if content:
            gemini_history.append({"role": role, "parts": [{"text": content}]})

    # 6. Build system prompt with current collected state
    system_prompt = _build_system_prompt(collected)

    # 7. Call Gemini
    try:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        client = genai.Client(api_key=api_key)

        # Start chat with history, then send new message
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
            history=gemini_history,
        )
        response = chat.send_message(actual_message or "Привет")
        raw = response.text or ""
    except Exception as e:
        logger.error("[gemini_call] %s", e)
        _save_ai_message(user_id, "Что-то пошло не так. Попробуй ещё раз.", None, user_chat_id)
        return JSONResponse(content={
            "ai_response": "Что-то пошло не так. Попробуй ещё раз.",
            "quick_replies": [],
            "onboarding_phase": "collecting",
            "pet_id": None,
            "input_type": "text",
        })

    # 8. Parse Gemini JSON response
    try:
        parsed = _parse_gemini_json(raw)
    except Exception as e:
        logger.error("[parse_gemini_json] raw=%r err=%s", raw, e)
        # Gemini returned non-JSON — treat raw as plain text
        parsed = {
            "text": raw.strip(),
            "quick_replies": [],
            "collected": {},
            "status": "collecting",
        }

    ai_text = parsed.get("text", "").strip()
    quick_replies = parsed.get("quick_replies") or []
    new_collected = parsed.get("collected") or {}
    status = parsed.get("status", "collecting")

    # 9. Merge collected fields
    collected = _merge_collected(collected, new_collected)

    # 10. Override status if we detect completion
    if status != "complete" and _is_complete(collected):
        status = "complete"

    # 11. Save merged collected to user flags
    user_flags["onboarding_collected"] = collected
    update_user_flags(user_id, user_flags)

    # 12. If complete: create pet, clear collected
    pet_id = None
    pet_card = None
    if status == "complete":
        pet_id = _create_pet(user_id, collected)
        if pet_id:
            # Clear onboarding data from flags
            user_flags["onboarding_collected"] = None
            update_user_flags(user_id, user_flags)

            # Build pet card for UI
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

            pet_card = {
                "name": collected.get("pet_name") or "Питомец",
                "species": species_display,
                "breed": collected.get("breed") or "—",
                "gender": gender_display,
                "age": age_display,
                "neutered": neutered_display,
                "avatar_url": None,
            }

    # 13. Detect input_type from quick_replies or message content
    input_type = "text"
    ai_text_lower = ai_text.lower()
    if any(w in ai_text_lower for w in ["фото", "паспорт", "снимок", "сфотографируй"]):
        input_type = "image"

    # 14. Save AI response to chat
    _save_ai_message(user_id, ai_text, pet_id, user_chat_id)

    return JSONResponse(content={
        "ai_response": ai_text,
        "quick_replies": quick_replies,
        "onboarding_phase": status,
        "pet_id": pet_id,
        "pet_card": pet_card,
        "input_type": input_type,
        "collected": collected,
    })
