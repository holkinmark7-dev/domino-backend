# routers/onboarding_instructions.py
# Step instructions and fallback text for AI-driven onboarding.

from routers.onboarding_utils import _decline_pet_name


def _get_step_instruction(step: str, collected: dict) -> str:
    """Return instruction for the current onboarding step."""
    owner = collected.get("owner_name", "")
    pet = collected.get("pet_name", "")
    species = collected.get("species", "")
    gender = collected.get("gender", "")
    hint = collected.get("_gender_hint", "")

    pet_gen = _decline_pet_name(pet, "gen") if pet else "питомца"
    pet_dat = _decline_pet_name(pet, "dat") if pet else "питомцу"
    pet_acc = _decline_pet_name(pet, "acc") if pet else "питомца"

    # ─── owner_name ───
    if step == "owner_name":
        if not collected.get("_input_hint") and not collected.get("_owner_name_refusals", 0):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Привет. Я Dominik — буду заботиться о твоём питомце вместе с тобой. Как тебя зовут?"\n'
                f"ЗАПРЕЩЕНО менять текст, добавлять слова, задавать другие вопросы."
            )
        return (
            f"Отреагируй коротко на то что написал пользователь. Одно предложение.\n"
            f"[QUESTION]Как тебя зовут?"
        )

    # ─── pet_name ───
    if step == "pet_name":
        return (
            f"Тепло поприветствуй {owner} — одно предложение с характером.\n"
            f"[QUESTION]Как зовут питомца?"
        )

    # ─── species_guess ───
    if step == "species_guess_dog":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} — ставлю на собаку. Угадал?"\n'
            f"ЗАПРЕЩЕНО менять текст."
        )
    if step == "species_guess_cat":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} — ставлю на кота. Угадал?"\n'
            f"ЗАПРЕЩЕНО менять текст."
        )

    # ─── goal ───
    if step == "goal":
        return (
            f"Тепло отреагируй на кличку {pet}. Одно предложение с характером.\n"
            f"[QUESTION]Чем могу помочь?"
        )

    # ─── species ───
    if step == "species":
        if collected.get("_exotic_attempt"):
            return (
                f"Объясни что пока работаешь только с кошками и собаками. Одно предложение.\n"
                f"[QUESTION]Кошка или собака есть?"
            )
        return (
            f"[QUESTION]{pet} — кошка или собака?"
        )

    # ─── passport_offer ───
    if step == "passport_offer":
        return (
            f"[QUESTION]Сфоткай ветпаспорт {pet_gen} — сам всё перенесу в карточку. Или заполним вручную."
        )

    # ─── breed ───
    if step == "breed":
        if collected.get("_breed_unknown"):
            return (
                f"[QUESTION]Можешь сфотографировать {pet_acc} — попробую определить породу. Или пропусти, метис тоже хорошо."
            )
        if collected.get("_breed_photo_requested"):
            return (
                f"[QUESTION]Жду фото {pet_gen} для определения породы."
            )
        if collected.get("_breed_clarification_options"):
            return (
                f"[QUESTION]Какой именно подвид у {pet_gen}?"
            )
        if collected.get("_awaiting_breed_text"):
            return (
                f"[QUESTION]Напиши породу {pet_gen} — какая?"
            )
        # default breed
        if species == "dog":
            breed_fact = f"Зная породу, подскажу про типичные болезни, питание, характер."
        else:
            breed_fact = f"Зная породу, подскажу про особенности здоровья и ухода."
        return (
            f"{breed_fact}\n"
            f"[QUESTION]Какой породы {pet}?"
        )

    # ─── birth_date ───
    if step == "birth_date":
        breed = collected.get("breed", "")
        if breed and breed != "Метис":
            return (
                f"Коротко отреагируй на породу {breed} — один факт с характером.\n"
                f"[QUESTION]Когда родился {pet}?"
            )
        return (
            f"[QUESTION]Когда родился {pet}?"
        )

    # ─── gender ───
    if step == "gender":
        age_reaction = ""
        age = collected.get("age_years")
        if age is not None and not collected.get("_age_reacted"):
            age_reaction = f"{pet_dat} уже {int(age)} — отреагируй на возраст коротко и тепло. "

        if hint == "male":
            return (
                f"{age_reaction}\n"
                f"[QUESTION]{pet} — мальчик?"
            )
        if hint == "female":
            return (
                f"{age_reaction}\n"
                f"[QUESTION]{pet} — девочка?"
            )
        return (
            f"{age_reaction}\n"
            f"[QUESTION]{pet} — мальчик или девочка?"
        )

    # ─── is_neutered ───
    if step == "is_neutered":
        gender_val = collected.get("gender", "")
        word = "стерилизована" if gender_val == "female" else "кастрирован"
        return (
            f"[QUESTION]{pet} {word}? Влияет на питание и режим."
        )

    # ─── avatar ───
    if step == "avatar":
        return (
            f"[QUESTION]Последний штрих — фото {pet_gen} для аватарки в профиле."
        )

    return "Продолжи разговор."


# ── Fallback text ──────────────────────────────────────────────────────────────

def _get_fallback_text(step: str, collected: dict) -> str:
    pet = collected.get("pet_name", "питомец")
    pet_gen = _decline_pet_name(pet, "gen")
    pet_dat = _decline_pet_name(pet, "dat")
    owner = collected.get("owner_name", "")
    fallbacks = {
        "owner_name": "Привет. Я Dominik — буду заботиться о твоём питомце вместе с тобой. Как тебя зовут?",
        "pet_name": f"{owner}, рассказывай — как зовут питомца?" if owner else "Как зовут питомца?",
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
