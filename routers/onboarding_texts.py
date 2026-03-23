"""
Тексты онбординга Domino Pets.
Каждое слово продумано. AI не используется.
Источник правды: dominik-system-v2.3.md
"""

from routers.onboarding_utils import _decline_pet_name


def _age_word(age: int) -> str:
    """Правильное склонение: 1 год, 2 года, 5 лет."""
    if age % 10 == 1 and age % 100 != 11:
        return f"{age} год"
    elif age % 10 in (2, 3, 4) and age % 100 not in (12, 13, 14):
        return f"{age} года"
    else:
        return f"{age} лет"


def get_step_text(step: str, collected: dict) -> str:
    """Возвращает готовый текст Dominik для текущего шага."""

    owner = collected.get("owner_name", "")
    pet = collected.get("pet_name", "")
    species = collected.get("species", "")
    gender = collected.get("gender", "")
    breed = collected.get("breed", "")
    age = collected.get("age_years")
    goal = collected.get("goal", "")

    pet_gen = _decline_pet_name(pet, "gen") if pet else "питомца"
    pet_dat = _decline_pet_name(pet, "dat") if pet else "питомцу"
    pet_acc = _decline_pet_name(pet, "acc") if pet else "питомца"

    refusals_owner = collected.get("_owner_name_refusals", 0)
    refusals_pet = collected.get("_pet_name_refusals", 0)

    # ═══════════════════════════════════
    # OWNER_NAME
    # ═══════════════════════════════════
    if step == "owner_name":
        if refusals_owner == 0:
            return "Привет. Я Dominik — буду заботиться о твоём питомце вместе с тобой. Как тебя зовут?"
        if refusals_owner == 1:
            return "Напиши имя — так проще общаться."
        if refusals_owner == 2:
            return "Любое имя или прозвище — мне просто нужно знать как к тебе обращаться."
        # 3+
        return "Ладно, буду звать Друг. Потом поменяешь если захочешь."

    # ═══════════════════════════════════
    # PET_NAME
    # ═══════════════════════════════════
    if step == "pet_name":
        if refusals_pet == 0:
            return f"{owner}, давай знакомиться с твоим питомцем — как его зовут?"
        if refusals_pet == 1:
            return "Напиши кличку питомца — кошки или собаки."
        if refusals_pet == 2:
            return "Просто кличка — одно слово. Бобик, Мурка, Рекс — что угодно."
        # 3+
        return "Ладно, назову Питомец. Потом поменяешь."

    # ═══════════════════════════════════
    # PHOTO_OFFER
    # ═══════════════════════════════════
    if step == "photo_offer":
        return f"{owner}, скинь фото {pet_gen} — узнаю породу и возраст."

    # ═══════════════════════════════════
    # SPECIES_GUESS
    # ═══════════════════════════════════
    if step == "species_guess_dog":
        return f"{pet} — ставлю на собаку. Угадал?"

    if step == "species_guess_cat":
        return f"{pet} — ставлю на кота. Угадал?"

    # ═══════════════════════════════════
    # GOAL
    # ═══════════════════════════════════
    if step == "goal":
        return f"Что важно для {pet_gen} — следить за здоровьем, прививки или что-то беспокоит?"

    # ═══════════════════════════════════
    # SPECIES
    # ═══════════════════════════════════
    if step == "species":
        if collected.get("_exotic_attempt"):
            return "С экзотикой пока не работаю. Кошка или собака есть?"
        return f"{pet} — кошка или собака?"

    # ═══════════════════════════════════
    # PASSPORT_OFFER
    # ═══════════════════════════════════
    if step == "passport_offer":
        return f"Если есть ветпаспорт — сфоткай, сам всё перенесу. Или заполним вручную."

    # ═══════════════════════════════════
    # BREED
    # ═══════════════════════════════════
    if step == "breed":
        if collected.get("_breed_unknown"):
            return f"Можешь сфоткать {pet_acc} — попробую определить породу. Или пропусти."
        if collected.get("_breed_photo_requested"):
            return f"Жду фото {pet_gen}."
        if collected.get("_breed_clarification_options"):
            options = collected.get("_breed_clarification_options", [])
            if options:
                names = ", ".join(options[:3])
                return f"Уточни — {names}?"
            return f"Уточни какая именно?"
        if collected.get("_awaiting_breed_text"):
            return f"Напиши породу {pet_gen}."
        return f"Какой породы {pet}?"

    # ═══════════════════════════════════
    # BIRTH_DATE
    # ═══════════════════════════════════
    if step == "birth_date":
        photo_age = collected.get("_photo_age_estimate", "")
        if photo_age:
            return f"По фото — {pet_dat} примерно {photo_age}. Если знаешь точную дату рождения — напиши. Или оставим так."
        breed = collected.get("breed", "")
        if breed and breed != "Метис":
            return None  # AI реакция на породу
        return f"Когда родился {pet}?"

    # ═══════════════════════════════════
    # GENDER
    # ═══════════════════════════════════
    if step == "gender":
        age_text = ""
        if age is not None and not collected.get("_age_reacted"):
            if age < 1:
                age_text = "Малыш ещё. "
            else:
                age_text = f"{_age_word(int(age))} — "
                if age <= 3:
                    age_text += "энергии на десятерых. "
                elif age <= 7:
                    age_text += "самый расцвет. "
                else:
                    age_text += "мудрый. "

        hint = collected.get("_gender_hint", "")
        if hint == "male":
            return f"{age_text}{pet} — мальчик, верно?"
        if hint == "female":
            return f"{age_text}{pet} — девочка, верно?"
        return f"{age_text}{pet} — мальчик или девочка?"

    # ═══════════════════════════════════
    # IS_NEUTERED
    # ═══════════════════════════════════
    if step == "is_neutered":
        word = "стерилизована" if gender == "female" else "кастрирован"
        return f"{pet} {word}?"

    # ═══════════════════════════════════
    # AVATAR
    # ═══════════════════════════════════
    if step == "avatar":
        return f"Последний штрих — фото {pet_gen} на аватарку."

    # ═══════════════════════════════════
    # COMPLETE
    # ═══════════════════════════════════
    if step == "complete":
        return None  # complete обрабатывается отдельно в onboarding_complete.py

    return f"Расскажи подробнее."
