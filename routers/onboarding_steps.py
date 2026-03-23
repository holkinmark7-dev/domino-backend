# routers/onboarding_steps.py
# Step logic for AI-driven onboarding.

from routers.onboarding_constants import (
    _DOG_NAMES, _CAT_NAMES, _FEMALE_CAT_NAMES, _NEUTRAL_NAMES,
    _POPULAR_DOG_BREEDS, _POPULAR_CAT_BREEDS, _BREED_CLARIFICATIONS,
)


def _get_current_step(collected: dict) -> str:
    """Determine current onboarding step based on collected data."""

    if not collected.get("owner_name"):
        return "owner_name"

    if not collected.get("pet_name"):
        return "pet_name"

    # Photo offer — после клички, перед видом
    if not collected.get("_photo_offer_done"):
        return "photo_offer"

    # Goal — после фото, перед видом
    if not collected.get("goal"):
        return "goal"

    # Угадывание вида — ТОЛЬКО для явных животных кличек
    if not collected.get("species") and not collected.get("_species_guessed"):
        name = (collected.get("pet_name") or "").lower().strip()
        if name in _DOG_NAMES:
            return "species_guess_dog"
        if name in _CAT_NAMES:
            return "species_guess_cat"

    # Вид — если не определён через угадывание
    if not collected.get("species"):
        return "species"

    # Паспорт — между species и breed (пропускается если фото заполнило breed)
    if not collected.get("_passport_skipped") and not collected.get("breed"):
        return "passport_offer"

    # Порода — один шаг, без subcategory
    if not collected.get("breed"):
        return "breed"

    # birth_date — спрашиваем ВСЕГДА, даже если age_years есть из фото
    if not collected.get("birth_date") and not collected.get("_age_skipped"):
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

    if step == "photo_offer":
        return [
            {"label": "Сфотографировать", "value": "PHOTO_OFFER_CAMERA", "preferred": True},
            {"label": "Пропустить", "value": "Пропустить", "preferred": False},
        ]

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
        photo_age = collected.get("_photo_age_estimate", "")
        if photo_age:
            return [
                {"label": f"Оставить {photo_age}", "value": f"__photo_age_confirm__{photo_age}", "preferred": True},
                {"label": "Указать дату", "value": "Выбрать дату", "preferred": False},
                {"label": "Возраст другой", "value": "Примерный возраст", "preferred": False},
            ]
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
