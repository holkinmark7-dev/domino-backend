# routers/onboarding_instructions.py
# Step instructions and fallback text for AI-driven onboarding.

from routers.onboarding_utils import _decline_pet_name


def _get_step_instruction(step: str, collected: dict) -> str:
    """Return Gemini instruction for current step. Exact texts with declensions."""
    owner = collected.get("owner_name", "")
    pet = collected.get("pet_name", "")
    species = collected.get("species", "")
    breed = collected.get("breed", "")
    gender = collected.get("gender", "")
    hint = collected.get("_detected_gender_hint", "neutral")

    pet_gen = _decline_pet_name(pet, "gen")
    pet_dat = _decline_pet_name(pet, "dat")

    if step == "owner_name":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Привет. Я Dominik — буду заботиться о твоём питомце вместе с тобой. Как тебя зовут?"\n'
            f"ЗАПРЕЩЕНО менять текст, добавлять слова, задавать другие вопросы."
        )

    if step == "pet_name":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{owner}, рассказывай — как зовут питомца?"\n'
            f"ЗАПРЕЩЕНО: 'Приятно познакомиться', два предложения, любые другие вопросы."
        )

    if step == "species_guess_dog":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} — ставлю на собаку. Угадал?"\n'
            f"ЗАПРЕЩЕНО: порода, возраст, пол."
        )

    if step == "species_guess_cat":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} — ставлю на кота. Угадал?"\n'
            f"ЗАПРЕЩЕНО: порода, возраст, пол."
        )

    if step == "goal":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet_dat} повезло с хозяином. Чем могу помочь?"\n'
            f"ЗАПРЕЩЕНО: вид, порода, возраст, пол, 'С чего начнём'."
        )

    # concern УБРАН

    if step == "species":
        goal = collected.get("goal", "")
        if collected.get("_exotic_attempt"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Пока работаю только с кошками и собаками. Кошка или собака есть?"\n'
                f"ЗАПРЕЩЕНО: любые другие темы."
            )
        if goal == "Есть тревога":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Чтобы разобраться — пара вопросов. Кошка или собака?"\n'
                f"ЗАПРЕЩЕНО: порода, возраст, пол."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Кошка или собака?"\n'
            f"ЗАПРЕЩЕНО: порода, возраст, пол."
        )

    if step == "passport_offer":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Если есть ветпаспорт — просто сфотографируй. Сам всё перенесу в карточку."\n'
            f"ЗАПРЕЩЕНО: порода, метис, возраст, пол, кастрация — НИ СЛОВА."
        )

    if step == "breed":
        if collected.get("_breed_unknown"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Загрузи фото {pet_gen} — определю породу сам. Или пропускаем."\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if collected.get("_breed_photo_requested"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Жду фото — отправь прямо сюда."\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if collected.get("_breed_clarification_options"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Уточни — какая именно?"\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if collected.get("_awaiting_breed_text"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Пиши — какая порода?"\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        if species == "dog":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Какая порода у {pet_gen}? Это поможет давать точные рекомендации."\n'
                f"ЗАПРЕЩЕНО: возраст, пол, кастрация, дата рождения."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Какая порода у {pet_gen}? Это поможет давать точные рекомендации."\n'
            f"ЗАПРЕЩЕНО: возраст, пол, кастрация, дата рождения."
        )

    if step == "birth_date":
        if breed and not collected.get("_age_approximate"):
            return (
                f"Начни с ОДНОГО короткого интересного факта о породе {breed} (максимум 8 слов). "
                f'Потом спроси: "Когда родился {pet}? Буду следить за графиком прививок и осмотров."\n'
                f"ЗАПРЕЩЕНО: пол, кастрация, второй вопрос.\n"
                f'ПРИМЕР: "Йорки — маленькие с характером на большую собаку. Когда родился {pet}?"'
            )
        if collected.get("_age_approximate"):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Сколько примерно — в годах или месяцах?"\n'
                f"ЗАПРЕЩЕНО: любые другие вопросы."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Когда родился {pet}? Буду следить за графиком прививок и осмотров."\n'
            f"ЗАПРЕЩЕНО: пол, кастрация, порода."
        )

    if step == "gender":
        age_reaction = ""
        age = collected.get("age_years")
        if age is not None and not collected.get("_age_reacted"):
            if age < 1:
                age_reaction = "Совсем малыш ещё. "
            elif age <= 2:
                age_reaction = "Энергии на десятерых. "
            elif age <= 5:
                age_reaction = "Золотые годы — сил полно, характер сложился. "
            elif age <= 8:
                age_reaction = "Зрелый, спокойный, знает чего хочет. "
            elif age <= 11:
                age_reaction = "Мудрый. Такие всё понимают без слов. "
            else:
                age_reaction = "Столько лет вместе — это настоящая история. "

        if hint == "male":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "{age_reaction}{pet} — мальчик?"\n'
                f"ЗАПРЕЩЕНО: кастрация, порода, повторять возраст числом."
            )
        if hint == "female":
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "{age_reaction}{pet} — девочка?"\n'
                f"ЗАПРЕЩЕНО: кастрация, порода, повторять возраст числом."
            )
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{age_reaction}{pet} — мальчик или девочка?"\n'
            f"ЗАПРЕЩЕНО: кастрация, порода, повторять возраст числом."
        )

    if step == "is_neutered":
        word = "стерилизована" if gender == "female" else "кастрирован"
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "{pet} {word}? Это влияет на питание и здоровье — хочу учитывать."\n'
            f"ЗАПРЕЩЕНО: любые другие вопросы."
        )

    if step == "avatar":
        return (
            f'Скажи РОВНО ЭТОТ ТЕКСТ: "Последний штрих — фото {pet_gen} для профиля."\n'
            f"ЗАПРЕЩЕНО: любые другие вопросы."
        )

    return f"Ответь коротко про {pet}."


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
