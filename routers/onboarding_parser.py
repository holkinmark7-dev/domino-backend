# routers/onboarding_parser.py
# User input parser for AI-driven onboarding.

import re
import logging
from datetime import date

from rapidfuzz import fuzz
from routers.services.breeds import ALL_BREEDS
from routers.onboarding_constants import (
    _BREED_CLARIFICATIONS, _BREED_SHORTCUTS,
)
from routers.onboarding_utils import (
    _parse_age, _parse_age_with_gemini, _parse_name, _parse_name_with_gemini,
    _validate_input_with_ai, _check_breed_subtypes,
    _parse_breed_with_gemini,
)

logger = logging.getLogger(__name__)


# ── User input parser ─────────────────────────────────────────────────────────

def _parse_user_input(msg: str, step: str, collected: dict, client=None) -> dict:
    if not msg or not msg.strip():
        return {}

    raw = msg.strip()
    low = raw.lower()
    clean = low.rstrip(".,!?;:\u2026")
    updates: dict = {}

    # ─── owner_name ───
    if step == "owner_name":
        # Явный отказ — увеличить счётчик
        refusal_words = ["не скажу", "аноним", "не хочу", "не твоё дело", "не твое дело",
                         "не буду", "отстань", "зачем тебе", "какая разница"]
        if any(w in low for w in refusal_words):
            count = collected.get("_owner_name_refusals", 0) + 1
            updates["_owner_name_refusals"] = count
            if count == 1:
                updates["_input_hint"] = "Мне нужно имя чтобы обращаться к тебе. Как тебя зовут?"
            elif count == 2:
                updates["_input_hint"] = "Без имени не смогу вести диалог — мне важно знать к кому обращаюсь."
            else:
                updates["_input_hint"] = "Понимаю. Видимо приложение сейчас не нужно. Если передумаешь — я здесь."
                updates["_onboarding_blocked"] = True
            return updates

        # Пустое
        if not raw or len(raw.strip()) == 0:
            return {}

        # ЕДИНСТВЕННЫЙ путь — AI
        try:
            ai_result = _validate_input_with_ai(raw, "owner_name", collected)
            logger.info("[ONB] owner_name AI: input='%s' result=%s", raw[:50], ai_result)
        except Exception as e:
            logger.error("[ONB] owner_name AI error: %s", e)
            ai_result = {"valid": False, "hint": "Как мне к тебе обращаться?"}

        if ai_result.get("valid") and ai_result.get("value"):
            name = ai_result["value"].strip()
            # Проверка кодом: минимум 2 буквы, начинается с заглавной
            if len(name) >= 2 and name[0].isupper():
                updates["owner_name"] = name
                updates["_onboarding_blocked"] = False
                updates["_owner_name_refusals"] = 0
                return updates

        # AI сказал невалидно или ошибка — эскалация
        count = collected.get("_owner_name_refusals", 0) + 1
        updates["_owner_name_refusals"] = count
        if count >= 3:
            updates["_input_hint"] = "Понимаю. Видимо приложение сейчас не нужно. Если передумаешь — я здесь."
            updates["_onboarding_blocked"] = True
        elif count == 2:
            updates["_input_hint"] = "Без имени не смогу вести диалог — мне важно знать к кому обращаюсь."
        else:
            updates["_input_hint"] = ai_result.get("hint", "Мне нужно имя чтобы обращаться к тебе. Как тебя зовут?")
        return updates

    # ─── pet_name ───
    elif step == "pet_name":
        # Отказ назвать кличку — эскалация
        refusal_words_pet = ["не знаю", "нет имени", "без имени", "пока нет",
                             "не скажу", "не хочу", "отстань", "зачем"]
        if any(w in low for w in refusal_words_pet):
            count = collected.get("_pet_name_refusals", 0) + 1
            updates["_pet_name_refusals"] = count
            if count == 1:
                updates["_input_hint"] = "Мне нужна кличка чтобы вести карточку питомца. Как зовут?"
            elif count == 2:
                updates["_input_hint"] = "Без клички не получится создать профиль. Как зовут питомца?"
            else:
                updates["_input_hint"] = "Понимаю. Видимо сейчас не время. Если передумаешь — я здесь."
                updates["_onboarding_blocked"] = True
            return updates

        # Пустое
        if not raw or len(raw.strip()) == 0:
            return {}

        # ЕДИНСТВЕННЫЙ путь — AI
        try:
            ai_result = _validate_input_with_ai(raw, "pet_name", collected)
            logger.info("[ONB] pet_name AI: input='%s' result=%s", raw[:50], ai_result)
        except Exception as e:
            logger.error("[ONB] pet_name AI error: %s", e)
            ai_result = {"valid": False, "hint": "Как зовут питомца?"}

        if ai_result.get("valid") and ai_result.get("value"):
            name = ai_result["value"].strip()
            if len(name) >= 2 and name[0].isupper():
                updates["pet_name"] = name
                updates["_onboarding_blocked"] = False
                updates["_pet_name_refusals"] = 0
                return updates

        # AI сказал невалидно — эскалация
        count = collected.get("_pet_name_refusals", 0) + 1
        updates["_pet_name_refusals"] = count
        if count >= 3:
            updates["_input_hint"] = "Понимаю. Видимо сейчас не время. Если передумаешь — я здесь."
            updates["_onboarding_blocked"] = True
        elif count == 2:
            updates["_input_hint"] = "Без клички не получится создать профиль. Как зовут питомца?"
        else:
            updates["_input_hint"] = ai_result.get("hint", "Мне нужна кличка чтобы вести карточку питомца. Как зовут?")
        return updates

    # ─── photo_offer ───
    elif step == "photo_offer":
        if any(w in low for w in ("пропуст", "нет фото", "не хочу", "потом", "скип", "нет")):
            updates["_photo_offer_done"] = True
            return updates
        # Фото обрабатывается через breed_detection_data, не текстом
        updates["_photo_offer_refusals"] = collected.get("_photo_offer_refusals", 0) + 1
        return updates

    # ─── photo confirm/reject (после анализа фото) ───
    elif raw == "__photo_confirm__":
        updates["_photo_offer_done"] = True
        photo_breeds = collected.get("_photo_breeds", [])
        if photo_breeds:
            updates["breed"] = photo_breeds[0].get("name_ru", photo_breeds[0]) if isinstance(photo_breeds[0], dict) else photo_breeds[0]
        color = collected.get("_photo_color")
        if color:
            updates["color"] = color
        age_est = collected.get("_photo_age_estimate")
        if age_est:
            # Парсить "~3 года" → age_years
            import re as _re
            m = _re.search(r'(\d+)', str(age_est))
            if m:
                updates["age_years"] = int(m.group(1))
        # species уже записан при обработке фото
        return updates

    elif raw == "__photo_reject__":
        updates["_photo_offer_done"] = True
        return updates

    # ─── species_guess_dog ───
    elif step == "species_guess_dog":
        if any(w in clean for w in ["да", "пёс", "пес", "собака", "угадал"]):
            updates["species"] = "dog"
        else:
            updates["_species_guessed"] = True

    # ─── species_guess_cat ───
    elif step == "species_guess_cat":
        if "кошка" in clean:
            updates["species"] = "cat"
            updates["gender"] = "female"
        elif "кот" in clean.split() or clean in ("кот", "да кот", "да, кот"):
            updates["species"] = "cat"
            updates["gender"] = "male"
        elif any(w in clean for w in ["да", "угадал"]):
            updates["species"] = "cat"
            updates["gender"] = "male"
        else:
            updates["_species_guessed"] = True

    # ─── goal ───
    elif step == "goal":
        goal_map = {
            "слежу за здоровьем": "Слежу за здоровьем",
            "прививки и плановое": "Прививки и плановое",
            "веду дневник": "Веду дневник",
            "кое-что беспокоит": "Есть тревога",
            "кое что беспокоит": "Есть тревога",
            "беспокоит": "Есть тревога",
            "тревога": "Есть тревога",
            "тревожит": "Есть тревога",
            "болеет": "Есть тревога",
            "болит": "Есть тревога",
            "плохо": "Есть тревога",
            "здоровь": "Слежу за здоровьем",
            "привив": "Прививки и плановое",
            "вакцин": "Прививки и плановое",
            "дневник": "Веду дневник",
            "записи": "Веду дневник",
        }
        for key, value in goal_map.items():
            if key in low:
                updates["goal"] = value
                break
        if not updates.get("goal") and len(raw) > 2:
            # Фильтр: вид животного — это не goal
            species_words = {"собака", "кошка", "кот", "пёс", "пес", "щенок", "котёнок", "котенок"}
            if clean not in species_words:
                updates["goal"] = raw
            # Если вид — шаг повторится, AI переспросит
        if updates.get("goal") == "Есть тревога":
            updates["_concern_heard"] = True

    # ─── concern УБРАН ───

    # ─── species ───
    elif step == "species":
        if clean == "кот" or clean.startswith("кот "):
            updates["species"] = "cat"
            updates["gender"] = "male"
            updates["_onboarding_blocked"] = False
            updates["_species_refusals"] = 0
        elif "кошка" in clean:
            updates["species"] = "cat"
            updates["gender"] = "female"
            updates["_onboarding_blocked"] = False
            updates["_species_refusals"] = 0
        elif any(w in clean for w in ["собака", "пёс", "пес", "щенок"]):
            updates["species"] = "dog"
            updates["_onboarding_blocked"] = False
            updates["_species_refusals"] = 0
        else:
            exotic = [
                "попугай", "хомяк", "рыбка", "черепаха", "кролик",
                "крыса", "морская свинка", "хорёк", "хорек",
                "ящерица", "змея", "шиншилла", "птица", "канарейка",
                "игуана", "хамелеон", "паук", "улитка",
            ]
            if any(w in low for w in exotic):
                updates["_exotic_attempt"] = True

            # Ни вид, ни экзотика — считаем как отказ
            if not updates.get("species") and not updates.get("_exotic_attempt"):
                count = collected.get("_species_refusals", 0) + 1
                updates["_species_refusals"] = count
                if count == 1:
                    updates["_input_hint"] = "Мне нужно знать — кошка или собака. Без этого не смогу помочь."
                elif count == 2:
                    updates["_input_hint"] = "Кошка или собака? Это важно для рекомендаций по здоровью."
                else:
                    updates["_input_hint"] = "Понимаю. Если передумаешь — я здесь."
                    updates["_onboarding_blocked"] = True

    # ─── passport_offer ───
    elif step == "passport_offer":
        if "сфотографирую" in low:
            updates["_passport_photo_requested"] = True
        elif any(w in low for w in [
            "вручную", "паспорта нет", "нет паспорта",
            "лучше вручную", "нет", "без паспорта", "пропуст",
        ]):
            updates["_passport_skipped"] = True

    # ─── breed ───
    elif step == "breed":
        # === Выбор из предложенных подвидов — записать НАПРЯМУЮ ===
        current_opts = collected.get("_breed_clarification_options")
        if current_opts:
            # Точное совпадение (кнопка нажата)
            for o in current_opts:
                if raw == o or low == o.lower():
                    updates["breed"] = o
                    updates["_breed_clarification_options"] = None
                    return updates
            # Нечёткое совпадение (текст похож на подвид)
            for o in current_opts:
                if fuzz.ratio(low, o.lower()) >= 75:
                    updates["breed"] = o
                    updates["_breed_clarification_options"] = None
                    return updates
            # "Другая порода" обработается ниже — НЕ return

        # === "Не знаю" / "Другая порода" / "Пропустить" / BREED_PHOTO / метис ===
        if any(w in low for w in ["не знаю породу", "не знаю", "хз", "без понятия"]):
            updates["_breed_unknown"] = True
            return updates
        if "другая порода" in low:
            updates["_breed_clarification_options"] = None
            updates["_awaiting_breed_text"] = True
            return updates
        if clean in ("пропустить", "пропуск", "скип"):
            updates["breed"] = "Метис"
            return updates
        if raw == "BREED_PHOTO":
            updates["_breed_photo_requested"] = True
            return updates
        metis_words = [
            "дворняга", "дворняжка", "метис", "беспородная",
            "беспородный", "дворняга или метис", "двортерьер",
            "помесь", "смесь",
        ]
        if any(w in low for w in metis_words):
            updates["breed"] = "Метис"
            return updates

        # === УРОВЕНЬ 0: Словарь подвидов ===
        clarify = _BREED_CLARIFICATIONS.get(clean)
        if not clarify:
            for key in _BREED_CLARIFICATIONS:
                if key.startswith(clean) and len(clean) >= 3:
                    clarify = _BREED_CLARIFICATIONS[key]
                    break
        if clarify:
            updates["_breed_clarification_options"] = clarify
            return updates

        # === Словарь сокращений (с проверкой подвидов) ===
        shortcut = _BREED_SHORTCUTS.get(low)
        if shortcut:
            subtype_result = _check_breed_subtypes(shortcut, collected.get("species", "dog"))
            if not subtype_result.get("exact") and subtype_result.get("options"):
                updates["_breed_clarification_options"] = subtype_result["options"]
                return updates
            updates["breed"] = subtype_result.get("breed", shortcut)
            return updates

        # === УРОВЕНЬ 1: Rapidfuzz (порог 85%) ===
        best_match = None
        best_score = 0
        for breed_name in ALL_BREEDS:
            score = fuzz.ratio(low, breed_name.lower())
            if score > best_score:
                best_score = score
                best_match = breed_name

        if best_score >= 70 and best_match:
            # Быстрый кэш — словарь подвидов
            if low in _BREED_CLARIFICATIONS:
                updates["_breed_clarification_options"] = _BREED_CLARIFICATIONS[low]
                return updates
            # AI проверка подвидов — для всего что не в словаре
            subtype_result = _check_breed_subtypes(best_match, collected.get("species", "dog"))
            if subtype_result.get("exact"):
                updates["breed"] = subtype_result.get("breed", best_match)
                return updates
            elif subtype_result.get("options"):
                updates["_breed_clarification_options"] = subtype_result["options"]
                return updates
            # Fallback — записать как есть
            updates["breed"] = best_match
            return updates

        # === УРОВЕНЬ 2: AI парсинг ===
        if client:
            result = _parse_breed_with_gemini(raw, collected.get("species", "dog"), client)
            if result.get("breed"):
                breed_low = result["breed"].lower()
                # Быстрый кэш
                if breed_low in _BREED_CLARIFICATIONS:
                    updates["_breed_clarification_options"] = _BREED_CLARIFICATIONS[breed_low]
                    return updates
                # AI проверка подвидов
                subtype_result = _check_breed_subtypes(result["breed"], collected.get("species", "dog"))
                if subtype_result.get("exact"):
                    updates["breed"] = subtype_result.get("breed", result["breed"])
                    return updates
                elif subtype_result.get("options"):
                    updates["_breed_clarification_options"] = subtype_result["options"]
                    return updates
                updates["breed"] = result["breed"]
            elif result.get("needs_clarification") and result.get("options"):
                updates["_breed_clarification_options"] = result["options"]

    # ─── birth_date ───
    elif step == "birth_date":
        if clean in ("выбрать дату", "знаю дату рождения", "знаю дату", "введу дату"):
            updates["_wants_date_picker"] = True
            return updates
        if clean in ("примерный возраст", "примерно"):
            updates["_age_approximate"] = True
            updates["_wants_date_picker"] = False
            return updates
        if clean in ("не знаю", "хз", "без понятия"):
            updates["_age_skipped"] = True
            updates["_wants_date_picker"] = False
            return updates
        updates["_wants_date_picker"] = False
        updates["_age_approximate"] = False
        date_match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", raw.strip())
        if date_match:
            day, month, year = date_match.groups()
            try:
                bd = date(int(year), int(month), int(day))
                today = date.today()
                if bd > today:
                    return {}
                if (today.year - bd.year) > 30:
                    return {}
                updates["birth_date"] = f"{year}-{month}-{day}"
                age = today.year - bd.year - (
                    (today.month, today.day) < (bd.month, bd.day)
                )
                updates["age_years"] = age
            except (ValueError, TypeError):
                return {}
            return updates
        date_match2 = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw.strip())
        if date_match2:
            year, month, day = date_match2.groups()
            try:
                bd = date(int(year), int(month), int(day))
                today = date.today()
                if bd > today or (today.year - bd.year) > 30:
                    return {}
                updates["birth_date"] = f"{year}-{month}-{day}"
                age = today.year - bd.year - (
                    (today.month, today.day) < (bd.month, bd.day)
                )
                updates["age_years"] = age
            except (ValueError, TypeError):
                return {}
            return updates
        age_result = _parse_age(raw)
        if age_result:
            updates.update(age_result)
        elif client:
            age_result = _parse_age_with_gemini(raw, client)
            if age_result:
                updates.update(age_result)

    # ─── gender ───
    elif step == "gender":
        if any(w in clean for w in ["мальчик", "кобель", "самец", "пацан", "парень", "мальч"]):
            updates["gender"] = "male"
        elif any(w in clean for w in ["девочка", "сука", "самка", "девоч"]):
            updates["gender"] = "female"
        elif clean in ("да", "ага", "верно", "точно", "угу", "да да", "ну да"):
            hint = collected.get("_detected_gender_hint", "neutral")
            if hint == "male":
                updates["gender"] = "male"
            elif hint == "female":
                updates["gender"] = "female"
        elif clean in ("нет", "не", "неа"):
            hint = collected.get("_detected_gender_hint", "neutral")
            if hint == "male":
                updates["gender"] = "female"
            elif hint == "female":
                updates["gender"] = "male"

    # ─── is_neutered ───
    elif step == "is_neutered":
        if clean in ("да", "ага", "угу", "кастрирован", "стерилизована",
                      "кастрирована", "стерилизован", "давно", "да давно"):
            updates["is_neutered"] = True
        elif clean in ("нет", "не", "неа", "нет ещё", "нет еще", "пока нет"):
            updates["is_neutered"] = False

    # ─── avatar ───
    elif step == "avatar":
        logger.info("[ONB] avatar: raw='%s' low='%s' clean='%s'", raw, low, clean)
        if raw == "AVATAR_PHOTO":
            logger.info("[ONB] avatar: AVATAR_PHOTO received")
            pass
        elif any(w in low for w in [
            "пропустить", "пропуск", "потом", "позже",
            "не сейчас", "скип", "нет", "не хочу",
            "skip", "пропущу", "без фото", "не надо",
            "не буду", "нет фото", "пас",
        ]):
            updates["_avatar_skipped"] = True
            logger.info("[ONB] avatar: SKIPPED via '%s'", raw)
        else:
            logger.info("[ONB] avatar: UNRECOGNIZED '%s' — treating as skip", raw)
            updates["_avatar_skipped"] = True

    # --- Бонусный парсинг: извлечь species из любого сообщения ---
    if raw and "species" not in collected and "species" not in updates:
        msg_l = raw.lower()
        if any(w in msg_l for w in ("собак", "пёс", "пес ", "щенок", "щенк")):
            updates["species"] = "dog"
        elif any(w in msg_l for w in ("кот ", "кошк", "котён", "кошеч")):
            updates["species"] = "cat"

    return updates
