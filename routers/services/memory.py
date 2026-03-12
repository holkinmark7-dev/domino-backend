from supabase import create_client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
import json
import logging

logger = logging.getLogger(__name__)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def ensure_user_exists(user_id: str):
    supabase.table("users").upsert(
        {"id": user_id},
        on_conflict="id"
    ).execute()


def save_event(
    user_id: str,
    pet_id: str,
    event_type: str,
    content,
    episode_id: str = None,
    metadata: dict = None,
    escalation_level: str = "LOW",
    urgency_score: float = 0,
):
    """
    Универсальное сохранение события.
    content — строка или dict (текст сообщения / описание события).
    metadata — структурированные данные: vitals, симптомы, extracted LLM данные.
    """
    if isinstance(content, dict):
        content = json.dumps(content, ensure_ascii=False)

    row = {
        "user_id": user_id,
        "pet_id": pet_id,
        "type": event_type,
        "content": content,
        "escalation_level": escalation_level,
        "urgency_score": urgency_score,
        "metadata": metadata or {},
    }

    if episode_id:
        row["episode_id"] = episode_id

    data = supabase.table("events").insert(row).execute()
    return data.data


def save_medical_event(
    user_id: str,
    pet_id: str,
    structured_data: dict,
    source_chat_id: str = None,
    episode_id: str = None,
    escalation_level: str = "LOW",
    urgency_score: float = 0,
):
    """
    Сохраняет структурированное медицинское событие.
    structured_data идёт в metadata (jsonb), не в content.
    """
    if not structured_data or "error" in structured_data:
        return None

    # Краткое текстовое описание для content
    symptoms = structured_data.get("symptoms") or []
    summary = ", ".join(symptoms) if symptoms else "medical_event"
    if source_chat_id:
        structured_data["source_chat_id"] = source_chat_id

    return save_event(
        user_id=user_id,
        pet_id=pet_id,
        event_type="medical_event",
        content=summary,
        episode_id=episode_id,
        metadata=structured_data,
        escalation_level=escalation_level,
        urgency_score=urgency_score,
    )


def get_recent_events(pet_id: str, limit: int = 10):
    """Возвращает последние события питомца."""
    data = (
        supabase
        .table("events")
        .select("*")
        .eq("pet_id", pet_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return data.data


def get_pet_profile(pet_id: str):
    """Возвращает профиль питомца + медкарту."""
    data = (
        supabase
        .table("pets")
        .select("*")
        .eq("id", pet_id)
        .single()
        .execute()
    )
    profile = data.data or {}

    try:
        med_data = (
            supabase
            .table("pet_medical_profile")
            .select("*")
            .eq("pet_id", pet_id)
            .single()
            .execute()
        )
        profile["medical"] = med_data.data if med_data.data else None
    except Exception as e:
        logger.error("[get_pet_profile] medical profile error pet_id=%s: %s", pet_id, e)
        profile["medical"] = None

    return profile


def get_medical_events(pet_id: str, limit: int = 50):
    """Возвращает медицинские события. metadata уже jsonb — парсинг не нужен."""
    data = (
        supabase
        .table("events")
        .select("*")
        .eq("pet_id", pet_id)
        .eq("type", "medical_event")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    events = data.data

    # content — текстовая строка, metadata — уже dict (jsonb из Supabase)
    # Для обратной совместимости: если metadata пустой, пробуем парсить content
    for event in events:
        if not event.get("metadata") and event.get("content"):
            try:
                parsed = json.loads(event["content"])
                if isinstance(parsed, dict):
                    event["metadata"] = parsed
            except (json.JSONDecodeError, ValueError):
                pass

    return events


def update_pet_profile(pet_id: str, fields: dict):
    """Обновляет поля паспорта питомца."""
    if not fields:
        return None
    try:
        data = (
            supabase
            .table("pets")
            .update(fields)
            .eq("id", pet_id)
            .execute()
        )
        return data.data
    except Exception as e:
        logger.error("[update_pet_profile] pet_id=%s error=%s", pet_id, e)
        return None


def upsert_pet_medical_profile(pet_id: str, fields: dict):
    """
    Создаёт или обновляет медкарту питомца.
    Использует UNIQUE(pet_id) constraint — больше не нужен ручной select.
    """
    if not fields:
        return None
    try:
        fields["pet_id"] = pet_id
        data = (
            supabase
            .table("pet_medical_profile")
            .upsert(fields, on_conflict="pet_id")
            .execute()
        )
        return data.data
    except Exception as e:
        logger.error("[upsert_pet_medical_profile] pet_id=%s error=%s", pet_id, e)
        return None


def get_onboarding_status(pet_id: str, user_id: str = None) -> dict:
    """
    Возвращает статус онбординга.
    Обязательные: species, name, gender, neutered, age
    Необязательные: breed, color, features, chip_id, stamp_id
    """
    REQUIRED_FIELDS = ["species", "name", "gender", "neutered", "age"]
    OPTIONAL_FIELDS = ["breed", "color", "features", "chip_id", "stamp_id"]

    profile = get_pet_profile(pet_id)
    if not profile:
        return {"complete": False, "next_question": "species", "phase": "required"}

    for field in REQUIRED_FIELDS:
        if field == "age":
            skipped = profile.get("birth_date_skipped", False)
        else:
            skipped = profile.get(f"{field}_skipped", False)
        if field == "neutered":
            has_value = profile.get("neutered") is not None
        elif field == "age":
            has_value = bool(profile.get("birth_date") or profile.get("age_years"))
        else:
            has_value = bool(profile.get(field))
        if not has_value and not skipped:
            return {"complete": False, "next_question": field, "phase": "required"}

    for field in OPTIONAL_FIELDS:
        val = profile.get(field)
        skipped = profile.get(f"{field}_skipped", False)
        if val is None and not skipped:
            return {"complete": False, "next_question": field, "phase": "optional"}

    return {"complete": True, "next_question": None, "phase": "done"}


def get_owner_name(user_id: str) -> str | None:
    """Возвращает имя владельца."""
    try:
        result = supabase.table("users").select("owner_name").eq("id", user_id).single().execute()
        return result.data.get("owner_name") if result.data else None
    except Exception:
        return None


def save_owner_name(user_id: str, name: str) -> bool:
    """Сохраняет имя владельца."""
    try:
        supabase.table("users").update({"owner_name": name}).eq("id", user_id).execute()
        return True
    except Exception:
        return False


def get_user_flags(user_id: str) -> dict:
    """Возвращает flags из таблицы users."""
    try:
        result = supabase.table("users").select("flags").eq("id", user_id).single().execute()
        return result.data.get("flags") or {} if result.data else {}
    except Exception:
        return {}


def update_user_flags(user_id: str, flags: dict) -> bool:
    """Обновляет flags в таблице users (merge)."""
    try:
        current = get_user_flags(user_id)
        current.update(flags)
        supabase.table("users").update({"flags": current}).eq("id", user_id).execute()
        return True
    except Exception:
        return False


def save_vaccines(pet_id: str, vaccines: list) -> None:
    """
    Save vaccines from passport OCR to pet_vaccines table.
    Upsert by (pet_id, name, date) to prevent duplicates on re-scan.
    """
    for vaccine in vaccines:
        record = {
            "pet_id": pet_id,
            "name": vaccine.get("name") if isinstance(vaccine, dict) else vaccine.name,
            "date": vaccine.get("date") if isinstance(vaccine, dict) else vaccine.date,
            "next_date": vaccine.get("next_date") if isinstance(vaccine, dict) else vaccine.next_date,
            "batch_number": vaccine.get("batch_number") if isinstance(vaccine, dict) else vaccine.batch_number,
            "source": "passport_ocr",
        }
        try:
            supabase.table("pet_vaccines").upsert(
                record, on_conflict="pet_id,name,date"
            ).execute()
        except Exception as e:
            logger.error("[save_vaccines] pet_id=%s vaccine=%s error=%s", pet_id, record.get("name"), e)