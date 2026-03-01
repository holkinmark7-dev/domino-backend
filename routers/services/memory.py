from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
import json

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def save_event(user_id: str, pet_id: str, event_type: str, content):
    """
    Универсальное сохранение события.
    content может быть строкой или dict.
    """

    if isinstance(content, dict):
        content = json.dumps(content)

    data = supabase.table("events").insert({
        "user_id": user_id,
        "pet_id": pet_id,
        "type": event_type,
        "content": content
    }).execute()

    return data.data


def save_medical_event(user_id: str, pet_id: str, structured_data: dict, source_chat_id: str = None):
    """
    Сохраняет структурированное медицинское событие
    """

    # Если extraction сломался — не сохраняем
    if not structured_data or "error" in structured_data:
        return None

    if source_chat_id:
        structured_data["source_chat_id"] = source_chat_id

    return save_event(
        user_id=user_id,
        pet_id=pet_id,
        event_type="medical_event",
        content=structured_data
    )


def get_recent_events(pet_id: str, limit: int = 10):
    """
    Возвращает последние события питомца
    """

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
    """
    Возвращает профиль питомца + медкарту если есть.
    """
    data = (
        supabase
        .table("pets")
        .select("*")
        .eq("id", pet_id)
        .single()
        .execute()
    )
    profile = data.data or {}

    # Читаем медкарту
    try:
        med_data = (
            supabase
            .table("pet_medical_profile")
            .select("*")
            .eq("pet_id", pet_id)
            .single()
            .execute()
        )
        if med_data.data:
            profile["medical"] = med_data.data
    except Exception:
        profile["medical"] = None

    return profile


def get_medical_events(pet_id: str, limit: int = 50):
    """
    Возвращает только медицинские события (medical_event)
    """

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

    # Парсим JSON content обратно в dict
    for event in events:
        try:
            event["content"] = json.loads(event["content"])
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[parse error] Failed to parse medical event content: {e}")
            event["content"] = {"error": "invalid_json"}

    return events


def update_pet_profile(pet_id: str, fields: dict):
    """
    Обновляет поля паспорта питомца в таблице pets.
    Только переданные поля — остальные не трогает.
    """
    if not fields:
        return None
    data = (
        supabase
        .table("pets")
        .update(fields)
        .eq("id", pet_id)
        .execute()
    )
    return data.data


def upsert_pet_medical_profile(pet_id: str, fields: dict):
    """
    Создаёт или обновляет медкарту питомца.
    """
    if not fields:
        return None

    # Проверяем есть ли уже запись
    existing = (
        supabase
        .table("pet_medical_profile")
        .select("id")
        .eq("pet_id", pet_id)
        .execute()
    )

    if existing.data:
        data = (
            supabase
            .table("pet_medical_profile")
            .update(fields)
            .eq("pet_id", pet_id)
            .execute()
        )
    else:
        fields["pet_id"] = pet_id
        data = (
            supabase
            .table("pet_medical_profile")
            .insert(fields)
            .execute()
        )
    return data.data


def get_onboarding_status(pet_id: str) -> dict:
    """
    Проверяет заполнены ли обязательные поля профиля.
    Возвращает: {complete: bool, missing: list[str], next_question: str}
    """
    profile = get_pet_profile(pet_id)
    if not profile:
        return {"complete": False, "missing": ["all"], "next_question": "name"}

    missing = []

    if not profile.get("name"):
        missing.append("name")
    if not profile.get("species"):
        missing.append("species")
    if not profile.get("gender"):
        missing.append("gender")
    if profile.get("neutered") is None:
        missing.append("neutered")
    if not profile.get("birth_date") and not profile.get("age_years"):
        missing.append("age")

    # Следующий вопрос — первый незаполненный
    next_q = missing[0] if missing else None

    return {
        "complete": len(missing) == 0,
        "missing": missing,
        "next_question": next_q
    }
