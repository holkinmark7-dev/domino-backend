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

    # ─── owner_name ───
    if step == "owner_name":
        if not collected.get("_input_hint") and not collected.get("_owner_name_refusals", 0):
            return (
                f'Скажи РОВНО ЭТОТ ТЕКСТ: "Привет. Я Dominik — буду заботиться о твоём питомце вместе с тобой. Как тебя зовут?"\n'
                f"ЗАПРЕЩЕНО менять текст, добавлять слова, задавать другие вопросы."
            )
        return (
            f"ЦЕЛЬ: узнать имя пользователя.\n"
            f"Он уже видел приветствие но не назвал имя.\n"
            f"1-2 предложения. Не повторяй приветствие.\n"
            f"РАМКИ: не спрашивай про питомца."
        )

    # ─── pet_name ───
    if step == "pet_name":
        return (
            f"ЦЕЛЬ: узнать кличку питомца.\n"
            f"Пользователя зовут {owner}.\n"
            f"ЗАЧЕМ: кличка — имя живого существа, к которому ты обращаешься в каждом разговоре.\n"
            f"1-2 предложения.\n"
            f'Пример тона: "{owner}, рассказывай — кто у тебя живёт?"\n'
            f"РАМКИ: не спрашивай вид, породу, возраст, пол."
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
            f"ЦЕЛЬ: узнать зачем пользователь пришёл.\n"
            f"Пользователя зовут {owner}, питомца — {pet}.\n"
            f"ЗАЧЕМ: от цели зависит как ты будешь помогать — профилактика, лечение или дневник.\n"
            f"1-2 предложения. Тепло отреагируй на кличку.\n"
            f"РАМКИ: не спрашивай вид, породу, возраст, пол."
        )

    # ─── species ───
    if step == "species":
        context = ""
        if collected.get("_exotic_attempt"):
            context = "Пользователь назвал экзотическое животное. Объясни что пока только кошки и собаки.\n"
        return (
            f"ЦЕЛЬ: узнать вид питомца — кошка или собака.\n"
            f"{context}"
            f"Пока ты работаешь только с кошками и собаками.\n"
            f"Одно предложение — только вопрос про вид.\n"
            f"РАМКИ: не спрашивай породу, возраст, пол. Не спрашивай что беспокоит. Только вид."
        )

    # ─── passport_offer ───
    if step == "passport_offer":
        return (
            f"ЦЕЛЬ: предложить сфотографировать ветпаспорт {pet_gen}.\n"
            f"ЗАЧЕМ: ты сам перенесёшь все данные из паспорта в карточку — породу, дату рождения, прививки. Не нужно вводить вручную.\n"
            f"1-2 предложения.\n"
            f"РАМКИ: не спрашивай породу, возраст, пол, кастрацию."
        )

    # ─── breed ───
    if step == "breed":
        species_label = "собаки" if species == "dog" else "кошки"

        if collected.get("_breed_unknown"):
            return (
                f"ЦЕЛЬ: помочь определить породу {pet_gen}.\n"
                f"ЗАЧЕМ: порода — ключ к здоровью. Питание, типичные болезни, поведение — всё зависит от породы.\n"
                f"Пользователь не знает породу. Предложи фото — ты можешь определить.\n"
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
                f"1 предложение — уточни какой именно.\n"
                f"РАМКИ: не спрашивай другое."
            )
        if collected.get("_awaiting_breed_text"):
            return (
                f"ЦЕЛЬ: узнать породу {pet_gen} текстом.\n"
                f"Пользователь не нашёл в списке. Попроси написать.\n"
                f"1 предложение.\n"
                f"РАМКИ: не спрашивай другое."
            )
        return (
            f"ЦЕЛЬ: узнать породу {pet_gen}.\n"
            f"ЗАЧЕМ: порода — ключ к здоровью. Питание, типичные болезни, поведение — всё зависит от породы. Зная породу ты помогаешь точнее.\n"
            f"1-2 предложения.\n"
            f"РАМКИ: не спрашивай возраст, пол, кастрацию, дату рождения."
        )

    # ─── birth_date ───
    if step == "birth_date":
        breed = collected.get("breed", "")
        if breed and breed != "Метис":
            return (
                f"ЦЕЛЬ: узнать когда родился {pet}.\n"
                f"ЗАЧЕМ: возраст определяет график прививок, режим питания, риски по здоровью.\n"
                f"Можешь коротко отреагировать на породу {breed} — одним фактом, к месту.\n"
                f"1-2 предложения.\n"
                f"РАМКИ: не спрашивай пол, кастрацию."
            )
        return (
            f"ЦЕЛЬ: узнать когда родился {pet}.\n"
            f"ЗАЧЕМ: возраст определяет график прививок, режим питания, риски по здоровью.\n"
            f"1-2 предложения.\n"
            f"РАМКИ: не спрашивай пол, кастрацию."
        )

    # ─── gender ───
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

    # ─── is_neutered ───
    if step == "is_neutered":
        gender_val = collected.get("gender", "")
        word = "стерилизована" if gender_val == "самка" else "кастрирован"
        return (
            f"ЦЕЛЬ: узнать {word} ли {pet}.\n"
            f"ЗАЧЕМ: влияет на питание, вес, поведение, риски по здоровью.\n"
            f"1-2 предложения. Деликатно.\n"
            f"РАМКИ: не спрашивай про другое."
        )

    # ─── avatar ───
    if step == "avatar":
        return (
            f"ЦЕЛЬ: попросить фото {pet_gen} для аватарки в профиле.\n"
            f"ЗАЧЕМ: фото станет аватаркой в карточке {pet_gen}. Это последний шаг знакомства.\n"
            f"1-2 предложения. Тепло, легко.\n"
            f"РАМКИ: не спрашивай про другое. Не придумывай другие причины зачем фото."
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
