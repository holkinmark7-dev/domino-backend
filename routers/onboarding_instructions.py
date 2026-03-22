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
        # Первое сообщение — шаблон (доверие нулевое)
        if not collected.get("_input_hint") and not collected.get("_owner_name_refusals", 0):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Привет. Я Dominik — буду заботиться о твоём питомце вместе с тобой. Как тебя зовут?"\n'
                f"ЗАПРЕЩЕНО менять текст, добавлять слова, задавать другие вопросы."
            )
        # Переспрос — Dominik думает сам
        return (
            f"ЦЕЛЬ: узнать имя пользователя.\n"
            f"Он уже видел приветствие но не назвал имя.\n"
            f"1-2 предложения. Не повторяй приветствие.\n"
            f"РАМКИ: не спрашивай про питомца."
        )

    if step == "pet_name":
        owner = collected.get("owner_name", "")
        return (
            f"ЦЕЛЬ: узнать кличку питомца.\n"
            f"Пользователя зовут {owner}.\n"
            f"Кличка — имя живого существа, не строчка в анкете.\n"
            f"1-2 предложения.\n"
            f'Пример тона: "{owner}, рассказывай — кто у тебя живёт?"\n'
            f"РАМКИ: не спрашивай вид, породу, возраст, пол."
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
            f"ЦЕЛЬ: узнать зачем пользователь пришёл.\n"
            f"Пользователя зовут {owner}, питомца — {pet}.\n"
            f"1-2 предложения. Тепло отреагируй на кличку.\n"
            f'Пример тона: "{pet_dat} повезло с хозяином. Чем могу помочь?"\n'
            f"РАМКИ: не спрашивай вид, породу, возраст, пол."
        )

    # concern УБРАН

    if step == "species":
        context = ""
        if collected.get("_exotic_attempt"):
            context = "Пользователь назвал экзотическое животное. Объясни что пока только кошки и собаки.\n"
        return (
            f"ЦЕЛЬ: узнать вид питомца — кошка или собака.\n"
            f"{context}"
            f"Пока ты работаешь только с кошками и собаками.\n"
            f"1-2 предложения.\n"
            f"РАМКИ: не спрашивай породу, возраст, пол."
        )

    if step == "passport_offer":
        return (
            f"ЦЕЛЬ: предложить сфотографировать ветпаспорт {pet_gen}.\n"
            f"Если есть — ты сам всё перенесёшь. Это экономит время.\n"
            f"1-2 предложения.\n"
            f"РАМКИ: не спрашивай породу, возраст, пол, кастрацию."
        )

    if step == "breed":
        species_label = "собаки" if species == "dog" else "кошки"

        if collected.get("_breed_unknown"):
            return (
                f"ЦЕЛЬ: помочь определить породу {pet_gen}.\n"
                f"Пользователь не знает породу. Предложи фото — ты можешь определить.\n"
                f"Объясни что без породы помогать сложнее, но не невозможно.\n"
                f"Метис или беспородная — это нормально, не минус.\n"
                f"1-2 предложения.\n"
                f"РАМКИ: не спрашивай возраст, пол, кастрацию."
            )
        if collected.get("_breed_photo_requested"):
            return (
                f"ЦЕЛЬ: получить фото {pet_gen} для определения породы.\n"
                f"Пользователь согласился сфотографировать. Жди фото.\n"
                f"1 предложение.\n"
                f"РАМКИ: не спрашивай другое."
            )
        if collected.get("_breed_clarification_options"):
            return (
                f"ЦЕЛЬ: уточнить подвид породы {pet_gen}.\n"
                f"Пользователь назвал общую породу, есть подвиды.\n"
                f"Уточни какой именно — коротко, дружелюбно.\n"
                f"1 предложение.\n"
                f"РАМКИ: не спрашивай другое."
            )
        if collected.get("_awaiting_breed_text"):
            return (
                f"ЦЕЛЬ: узнать породу {pet_gen} текстом.\n"
                f"Пользователь не нашёл в списке. Попроси написать.\n"
                f"1 предложение. Легко, без давления.\n"
                f"РАМКИ: не спрашивай другое."
            )
        return (
            f"ЦЕЛЬ: узнать породу {pet_gen}.\n"
            f"Порода — ключ к здоровью: питание, типичные болезни, поведение.\n"
            f"Зная породу, ты помогаешь на другом уровне.\n"
            f"1-2 предложения.\n"
            f"РАМКИ: не спрашивай возраст, пол, кастрацию, дату рождения."
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
        age_context = ""
        age = collected.get("age_years")
        if age is not None and not collected.get("_age_reacted"):
            age_context = f"{pet} — {int(age)} лет. Отреагируй на возраст коротко и тепло.\n"

        gender_context = ""
        if hint == "male":
            gender_context = f"По кличке похоже что {pet} — мальчик. Можешь предположить и уточнить.\n"
        elif hint == "female":
            gender_context = f"По кличке похоже что {pet} — девочка. Можешь предположить и уточнить.\n"

        return (
            f"ЦЕЛЬ: узнать пол {pet_gen} — мальчик или девочка.\n"
            f"{age_context}"
            f"{gender_context}"
            f"1-2 предложения.\n"
            f"РАМКИ: не спрашивай про кастрацию, породу."
        )

    if step == "is_neutered":
        gender_val = collected.get("gender", "")
        word = "стерилизована" if gender_val == "female" else "кастрирован"
        return (
            f"ЦЕЛЬ: узнать {word} ли {pet}.\n"
            f"Это влияет на питание и режим.\n"
            f"1-2 предложения. Деликатно, без давления.\n"
            f"РАМКИ: не спрашивай про другое."
        )

    if step == "avatar":
        return (
            f"ЦЕЛЬ: попросить фото {pet_gen} для профиля.\n"
            f"Это последний шаг знакомства.\n"
            f"1-2 предложения. Тепло, легко.\n"
            f"РАМКИ: не спрашивай про другое."
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
