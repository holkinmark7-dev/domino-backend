# routers/onboarding_ai.py
# AI-driven onboarding v2.0 — backend controls steps, Gemini writes text only.
# Main handler + re-exports for backward compatibility.

import json
import os
import logging

import openai
import anthropic
from google import genai
from google.genai import types
from fastapi.responses import JSONResponse

from routers.services.memory import get_user_flags, update_user_flags

# ── Module imports ────────────────────────────────────────────────────────────

from routers.onboarding_constants import (
    _DESIGN_DIR, _CHARACTER_PATH, _CHARACTER_TEXT,
    _MALE_NAMES, _FEMALE_NAMES, _DOG_NAMES, _CAT_NAMES,
    _FEMALE_CAT_NAMES, _NEUTRAL_NAMES,
    _POPULAR_DOG_BREEDS, _POPULAR_CAT_BREEDS,
    _BREED_CLARIFICATIONS, _BREED_SHORTCUTS,
)

from routers.onboarding_utils import (
    _decline_pet_name, _parse_age, _parse_age_with_gemini,
    _parse_name, _parse_name_with_gemini, _detect_name_gender,
    _validate_input_with_ai, _check_breed_subtypes, _parse_breed_with_gemini,
    _build_system_prompt, _remove_stop_phrases,
)

from routers.onboarding_steps import _get_current_step, _get_step_quick_replies
from routers.onboarding_instructions import _get_step_instruction, _get_fallback_text
from routers.onboarding_parser import _parse_user_input

from routers.onboarding_complete import (
    _create_pet, _build_pet_card, _build_completion_text,
    _load_chat_history, _save_ai_message, _save_user_message,
    supabase,
)

logger = logging.getLogger(__name__)


# ── Main handler ───────────────────────────────────────────────────────────────

def handle_onboarding_ai(
    user_id: str,
    message_text: str,
    passport_ocr_data: dict | None = None,
    breed_detection_data: dict | None = None,
) -> JSONResponse:
    """
    Handle one turn of AI-driven onboarding.
    Backend controls steps & quick_replies. Gemini writes text only.
    """
    # 1. Load accumulated collected data from user flags
    user_flags = get_user_flags(user_id)

    # Онбординг уже завершён — не обрабатывать повторно
    if user_flags.get("onboarding_complete"):
        logger.warning("[ONB] Already complete, returning guard response")
        return JSONResponse(content={
            "ai_response": "",
            "quick_replies": [],
            "onboarding_phase": "complete",
            "pet_id": user_flags.get("onboarding_pet_id"),
            "pet_card": None,
            "input_type": "text",
            "collected": {},
        })

    collected: dict = user_flags.get("onboarding_collected") or {}

    # Онбординг заблокирован (пользователь отказался 3 раза)
    if collected.get("_onboarding_blocked"):
        return JSONResponse(content={
            "ai_response": "Если передумаешь — я здесь. Напиши имя чтобы начать заново.",
            "quick_replies": [],
            "onboarding_phase": "collecting",
            "pet_id": None,
            "pet_card": None,
            "input_type": "text",
            "collected": {},
        })

    # 2. Handle special inputs (OCR, breed detection, avatar)
    actual_message = message_text
    logger.warning("[ONB] === NEW REQUEST === msg='%s' len=%d passport=%s breed=%s step_before_parse=%s",
                message_text[:80] if message_text else "EMPTY",
                len(message_text) if message_text else 0,
                bool(passport_ocr_data), bool(breed_detection_data),
                _get_current_step(collected))
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # 2a. Passport OCR
    if passport_ocr_data and passport_ocr_data.get("success") and passport_ocr_data.get("confidence", 0) >= 0.6:
        ocr_fields = {"pet_name", "breed", "birth_date", "gender", "is_neutered"}
        ocr_updates = {f: passport_ocr_data[f] for f in ocr_fields if passport_ocr_data.get(f) and not collected.get(f)}
        collected.update(ocr_updates)
        collected["_passport_skipped"] = True
        actual_message = "Паспорт отсканирован, данные заполнены автоматически."
    elif passport_ocr_data:
        collected["_passport_skipped"] = True
        actual_message = "Не удалось прочитать паспорт. Заполним вручную."

    # 2b. Photo / Breed detection
    elif breed_detection_data and breed_detection_data.get("success"):
        breeds = breed_detection_data.get("breeds", [])
        color = breed_detection_data.get("color")
        age_estimate = breed_detection_data.get("age_estimate")
        confidence = breed_detection_data.get("confidence", 0)

        # Записать данные в collected
        collected["_photo_offer_done"] = True
        if breeds:
            collected["_photo_breeds"] = [
                {"name_ru": b.get("name_ru", b) if isinstance(b, dict) else b,
                 "name_lat": b.get("name_lat", "") if isinstance(b, dict) else "",
                 "probability": b.get("probability", 0) if isinstance(b, dict) else 0}
                for b in breeds[:3]
            ]
            collected["_photo_confidence"] = confidence
        if color:
            collected["_photo_color"] = color
        if age_estimate:
            collected["_photo_age_estimate"] = age_estimate

        if breeds:
            top = breeds[0] if isinstance(breeds[0], dict) else {"name_ru": breeds[0], "probability": 0.5}
            top_name = top.get("name_ru", str(top))
            top_prob = top.get("probability", 0)

            # Определить species из контекста (vision обычно определяет кошка/собака)
            species_guess = "dog"  # дефолт — определится позже

            if top_prob > 0.7:
                # Уверен — одна порода, early return с photo_analysis
                collected["breed"] = top_name
                collected["species"] = species_guess
                if color:
                    collected["color"] = color

                user_chat_id = _save_user_message(user_id, "Фото питомца")
                user_flags["onboarding_collected"] = collected
                update_user_flags(user_id, user_flags)

                ai_text = f"{top_name} — уже вижу."
                _save_ai_message(user_id, ai_text, None, user_chat_id)

                logger.warning("[ONB] === PHOTO HIGH CONF === breed=%s conf=%.2f", top_name, top_prob)
                return JSONResponse(content={
                    "ai_response": ai_text,
                    "quick_replies": [
                        {"label": "Верно", "value": "__photo_confirm__", "preferred": True},
                        {"label": "Исправить", "value": "__photo_reject__", "preferred": False},
                    ],
                    "onboarding_phase": "collecting",
                    "pet_id": None,
                    "pet_card": None,
                    "input_type": "text",
                    "placeholder": "Написать...",
                    "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
                    "photo_analysis": {
                        "breed": top_name,
                        "breed_lat": top.get("name_lat", ""),
                        "confidence": round(top_prob * 100),
                        "color": color,
                        "age_estimate": age_estimate,
                        "species": species_guess,
                    },
                })
            else:
                # Не уверен — список пород
                user_chat_id = _save_user_message(user_id, "Фото питомца")
                user_flags["onboarding_collected"] = collected
                update_user_flags(user_id, user_flags)

                ai_text = "Похож на одну из пород — выбери правильную."
                _save_ai_message(user_id, ai_text, None, user_chat_id)

                breed_qr = [
                    {"label": (b.get("name_ru") if isinstance(b, dict) else b),
                     "value": (b.get("name_ru") if isinstance(b, dict) else b),
                     "preferred": i == 0}
                    for i, b in enumerate(breeds[:3])
                ]
                breed_qr.append({"label": "Другая порода", "value": "__photo_reject__", "preferred": False})

                breed_options = [
                    {"name": b.get("name_ru") if isinstance(b, dict) else b,
                     "probability": round((b.get("probability", 0) if isinstance(b, dict) else 0) * 100)}
                    for b in breeds[:3]
                ]

                logger.warning("[ONB] === PHOTO LOW CONF === breeds=%s", [b["name"] for b in breed_options])
                return JSONResponse(content={
                    "ai_response": ai_text,
                    "quick_replies": breed_qr,
                    "onboarding_phase": "collecting",
                    "pet_id": None,
                    "pet_card": None,
                    "input_type": "text",
                    "placeholder": "Написать...",
                    "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
                    "photo_analysis": {
                        "breeds": breed_options,
                        "color": color,
                        "age_estimate": age_estimate,
                        "species": species_guess,
                    },
                })
        else:
            actual_message = "Не удалось определить породу по фото. Заполним вручную."
            collected["_photo_offer_done"] = True

    # 2c. Avatar URL from message text
    elif message_text and message_text.startswith("avatar_url:"):
        avatar_url = message_text[len("avatar_url:"):]
        if avatar_url:
            collected["avatar_url"] = avatar_url
        actual_message = "Фото загружено."

    # 3. First _get_current_step — before parsing
    current_step = _get_current_step(collected)
    logger.warning("[ONB] BEFORE step=%s msg='%s' collected_keys=%s", current_step, actual_message[:50] if actual_message else "", [k for k in collected if not k.startswith("_")])

    # 4. If step is gender — compute hint BEFORE everything else
    if current_step == "gender" and not collected.get("_detected_gender_hint"):
        pet_name_val = collected.get("pet_name", "")
        name_lower = pet_name_val.lower()
        if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
            collected["_detected_gender_hint"] = "male"
        elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
            collected["_detected_gender_hint"] = "female"
        else:
            collected["_detected_gender_hint"] = _detect_name_gender(pet_name_val, client)

    # 5. Parse user input (text messages only, not special inputs)
    old_step = current_step  # сохранить перед парсингом
    if actual_message and actual_message == message_text:
        updates = _parse_user_input(actual_message, current_step, collected, client=client)
        collected.update(updates)
        logger.warning("[ONB] PARSED updates=%s", updates)
    else:
        logger.warning("[ONB] PARSE SKIPPED: actual='%s' original='%s' equal=%s",
                     actual_message[:50] if actual_message else "NONE",
                     message_text[:50] if message_text else "NONE",
                     actual_message == message_text)

    # Сброс одноразовых флагов
    if collected.get("birth_date") or collected.get("age_years") or collected.get("_age_skipped"):
        collected["_wants_date_picker"] = False
        collected["_age_approximate"] = False

    # 6. Second _get_current_step — after parsing
    current_step = _get_current_step(collected)
    logger.warning("[ONB] AFTER step=%s flags=%s", current_step, {k: v for k, v in collected.items() if k.startswith("_")})

    # Очистить hint если шаг изменился (успешный ввод)
    if current_step != old_step:
        collected.pop("_input_hint", None)

    # 7. If step changed to gender — compute hint for new step
    if current_step == "gender" and not collected.get("_detected_gender_hint"):
        pet_name_val = collected.get("pet_name", "")
        name_lower = pet_name_val.lower()
        if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
            collected["_detected_gender_hint"] = "male"
        elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
            collected["_detected_gender_hint"] = "female"
        else:
            collected["_detected_gender_hint"] = _detect_name_gender(pet_name_val, client)

    # 8. Save user message
    user_chat_id = None
    if actual_message and actual_message.strip():
        user_chat_id = _save_user_message(user_id, actual_message)

    # 9. Save collected to flags (before any early return)
    user_flags["onboarding_collected"] = collected
    update_user_flags(user_id, user_flags)

    # 9a. Сразу записать owner_name в users — для MoreScreen
    if collected.get("owner_name") and not user_flags.get("_owner_name_saved"):
        try:
            supabase.table("users").update(
                {"owner_name": collected["owner_name"]}
            ).eq("id", user_id).execute()
            user_flags["_owner_name_saved"] = True
            update_user_flags(user_id, user_flags)
        except Exception as e:
            logger.error("[ONB] owner_name save: %s", e)

    logger.warning("[ONB] === COMPLETE CHECK === step=%s avatar_skipped=%s avatar_url=%s breed=%s gender=%s neutered=%s",
                current_step,
                collected.get("_avatar_skipped"),
                collected.get("avatar_url"),
                collected.get("breed"),
                collected.get("gender"),
                collected.get("is_neutered"))

    # 10. Check completion — early return without Gemini
    if current_step == "complete":
        create_result = _create_pet(user_id, collected)
        if create_result:
            pet_id, short_id = create_result
            user_flags["onboarding_collected"] = None
            user_flags["onboarding_pet_id"] = pet_id
            user_flags["onboarding_complete"] = True
            update_user_flags(user_id, user_flags)

            pet_card = None  # TODO: заменить на walkthrough
            ai_text = _build_completion_text(collected)
            _save_ai_message(user_id, ai_text, pet_id, user_chat_id)

            logger.warning("[ONB] === SENDING TO FRONT === qr_count=0 qr_labels=[] input_type=text ai_text_len=%d phase=complete",
                           len(ai_text) if ai_text else 0)
            return JSONResponse(content={
                "ai_response": ai_text,
                "quick_replies": [{"label": "Познакомиться с приложением", "value": "WALKTHROUGH", "preferred": True}],
                "onboarding_phase": "complete",
                "pet_id": pet_id,
                "pet_card": pet_card,
                "input_type": "text",
                "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
            })

    # === DatePicker early return — НЕ вызываем AI ===
    if current_step == "birth_date" and collected.get("_wants_date_picker"):
        user_flags["onboarding_collected"] = collected
        update_user_flags(user_id, user_flags)

        logger.warning("[ONB] === SENDING TO FRONT === qr_count=0 qr_labels=[] input_type=date_picker ai_text_len=0 phase=collecting")
        return JSONResponse(content={
            "ai_response": "",
            "quick_replies": [],
            "onboarding_phase": "collecting",
            "pet_id": None,
            "pet_card": None,
            "input_type": "date_picker",
            "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
        })

    # 11. Compute quick replies (once)
    quick_replies = _get_step_quick_replies(current_step, collected, client)

    # --- Placeholder для поля ввода ---
    _STEP_PLACEHOLDERS = {
        "owner_name": "Твоё имя",
        "pet_name": "Например: Бобик, Мурка, Рекс",
        "breed": "Порода питомца",
        "birth_date": "ДД.ММ.ГГГГ",
    }
    placeholder = _STEP_PLACEHOLDERS.get(current_step, "Написать...")

    # 12. Готовые тексты (без AI)
    from routers.onboarding_texts import get_step_text

    scripted_text = get_step_text(current_step, collected)

    if scripted_text is not None:
        # Текст из кода — не вызываем AI
        ai_text = scripted_text
        logger.warning("[ONB] === SCRIPTED === step=%s text='%s'", current_step, ai_text[:80])
    else:
        # birth_date — единственный шаг где нужен AI (реакция на породу)
        breed = collected.get("breed", "")
        pet = collected.get("pet_name", "")
        birth_question = f"Когда родился {pet}?"

        if breed and breed != "Метис":
            try:
                ant_client = anthropic.Anthropic(
                    api_key=os.environ.get("ANTHROPIC_API_KEY", "")
                )
                resp = ant_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=25,
                    system=(
                        "Ты Dominik — ветеринарный друг. "
                        "Напиши ОДНУ фразу про породу, 3-7 слов. С характером. Без вопросов. "
                        "Примеры: 'Кавказец — серьёзный зверь, уважаю.', "
                        "'Хаски — энергии на десятерых.', "
                        "'Чихуахуа — мелкие, но характер не по размеру.'"
                    ),
                    messages=[{"role": "user", "content": f"Порода: {breed}"}],
                    temperature=0.7,
                )
                reaction = resp.content[0].text.strip()
                reaction = _remove_stop_phrases(reaction)
                # Убрать вопросы если AI добавил
                if "?" in reaction:
                    reaction = reaction.split("?")[0].rstrip()
                    if reaction and reaction[-1] not in ".!":
                        reaction += "."
                ai_text = f"{reaction}\n\n{birth_question}"
                logger.warning("[ONB] === BREED REACTION === breed=%s reaction='%s'",
                             breed, reaction)
            except Exception as e:
                logger.error("[ONB] breed reaction failed: %s", e)
                ai_text = birth_question
        else:
            ai_text = birth_question

    # 15. Fallback if empty response
    if not ai_text:
        ai_text = _get_fallback_text(current_step, collected)

    # 15a. Fallback имя/кличка при 3+ отказах
    if current_step == "owner_name" and collected.get("_owner_name_refusals", 0) >= 3:
        if not collected.get("owner_name"):
            collected["owner_name"] = "Друг"
    if current_step == "pet_name" and collected.get("_pet_name_refusals", 0) >= 3:
        if not collected.get("pet_name"):
            collected["pet_name"] = "Питомец"

    # 15b. Set _age_reacted after gender step uses age reaction
    if current_step == "gender" and collected.get("age_years") is not None:
        collected["_age_reacted"] = True
        user_flags["onboarding_collected"] = collected
        update_user_flags(user_id, user_flags)

    # 16. Save AI response
    _save_ai_message(user_id, ai_text, None, user_chat_id)

    # 17. Return response
    input_type = "date_picker" if (current_step == "birth_date" and collected.get("_wants_date_picker")) else "text"
    logger.warning("[ONB] RESPONSE step=%s qr=%s input_type=%s ai_text='%s'", current_step, [q["label"] for q in quick_replies], input_type, ai_text[:80] if ai_text else "")

    logger.warning("[ONB] === SENDING TO FRONT === qr_count=%d qr_labels=%s input_type=%s ai_text_len=%d phase=%s",
                   len(quick_replies) if isinstance(quick_replies, list) else 0,
                   [q["label"] for q in quick_replies][:5] if isinstance(quick_replies, list) else [],
                   input_type,
                   len(ai_text) if ai_text else 0,
                   "complete" if current_step == "complete" else "collecting")
    return JSONResponse(content={
        "ai_response": ai_text,
        "quick_replies": quick_replies,
        "onboarding_phase": "collecting",
        "pet_id": None,
        "pet_card": None,
        "input_type": input_type,
        "placeholder": placeholder,
        "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
    })


def prepare_onboarding_for_stream(
    user_id: str,
    message_text: str,
    passport_ocr_data: dict | None = None,
    breed_detection_data: dict | None = None,
) -> dict:
    """
    Run all onboarding logic EXCEPT the LLM call.
    Returns either:
      {"type": "final", "response": {...}}  — deterministic, send as one chunk
      {"type": "llm",   "oai_messages": [...], "metadata": {...}, "user_chat_id": ..., "collected": {...}}
    """
    # 1. Load state
    user_flags = get_user_flags(user_id)
    collected: dict = user_flags.get("onboarding_collected") or {}

    actual_message = message_text
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # 2. Special inputs (OCR, breed, avatar) — same as handle_onboarding_ai
    if passport_ocr_data and passport_ocr_data.get("success") and passport_ocr_data.get("confidence", 0) >= 0.6:
        ocr_fields = {"pet_name", "breed", "birth_date", "gender", "is_neutered"}
        ocr_updates = {f: passport_ocr_data[f] for f in ocr_fields if passport_ocr_data.get(f) and not collected.get(f)}
        collected.update(ocr_updates)
        collected["_passport_skipped"] = True
        actual_message = "Паспорт отсканирован, данные заполнены автоматически."
    elif passport_ocr_data:
        collected["_passport_skipped"] = True
        actual_message = "Не удалось прочитать паспорт. Заполним вручную."
    elif breed_detection_data and breed_detection_data.get("success"):
        breeds = breed_detection_data.get("breeds", [])
        color = breed_detection_data.get("color")
        if breeds:
            top = breeds[0]
            if top["probability"] > 0.7:
                collected["breed"] = top["name_ru"]
                if color:
                    collected["color"] = color
                actual_message = (
                    f"По фото определил породу: {top['name_ru']} "
                    f"({int(top['probability'] * 100)}% уверенность). "
                    f"Окрас: {color or 'не определён'}."
                )
            else:
                ai_text = "Вижу несколько вариантов по фото."
                breed_qr = [
                    {"label": f"{b['name_ru']} ({int(b['probability'] * 100)}%)", "value": b["name_ru"], "preferred": i == 0}
                    for i, b in enumerate(breeds[:3])
                ]
                breed_qr.append({"label": "Другая порода", "value": "Другая порода", "preferred": False})
                user_chat_id = _save_user_message(user_id, "Фото для определения породы")
                user_flags["onboarding_collected"] = collected
                update_user_flags(user_id, user_flags)
                _save_ai_message(user_id, ai_text, None, user_chat_id)
                return {"type": "final", "response": {
                    "ai_response": ai_text, "quick_replies": breed_qr,
                    "onboarding_phase": "collecting", "pet_id": None, "pet_card": None,
                    "input_type": "text",
                    "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
                }}
        else:
            actual_message = "Не удалось определить породу по фото."
    elif message_text and message_text.startswith("avatar_url:"):
        avatar_url = message_text[len("avatar_url:"):]
        if avatar_url:
            collected["avatar_url"] = avatar_url
        actual_message = "Фото загружено."

    # 3-7. Steps, parsing, gender hints — same as handle_onboarding_ai
    current_step = _get_current_step(collected)

    if current_step == "gender" and not collected.get("_detected_gender_hint"):
        pet_name_val = collected.get("pet_name", "")
        name_lower = pet_name_val.lower()
        if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
            collected["_detected_gender_hint"] = "male"
        elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
            collected["_detected_gender_hint"] = "female"
        else:
            collected["_detected_gender_hint"] = _detect_name_gender(pet_name_val, client)

    old_step = current_step
    if actual_message and actual_message == message_text:
        updates = _parse_user_input(actual_message, current_step, collected, client=client)
        collected.update(updates)

    if collected.get("birth_date") or collected.get("age_years") or collected.get("_age_skipped"):
        collected["_wants_date_picker"] = False
        collected["_age_approximate"] = False

    current_step = _get_current_step(collected)

    if current_step != old_step:
        collected.pop("_input_hint", None)

    if current_step == "gender" and not collected.get("_detected_gender_hint"):
        pet_name_val = collected.get("pet_name", "")
        name_lower = pet_name_val.lower()
        if name_lower in _MALE_NAMES or name_lower in _DOG_NAMES:
            collected["_detected_gender_hint"] = "male"
        elif name_lower in _FEMALE_NAMES or name_lower in _CAT_NAMES:
            collected["_detected_gender_hint"] = "female"
        else:
            collected["_detected_gender_hint"] = _detect_name_gender(pet_name_val, client)

    # 8. Save user message
    user_chat_id = None
    if actual_message and actual_message.strip():
        user_chat_id = _save_user_message(user_id, actual_message)

    # 9. Save collected
    user_flags["onboarding_collected"] = collected
    update_user_flags(user_id, user_flags)

    if collected.get("owner_name") and not user_flags.get("_owner_name_saved"):
        try:
            supabase.table("users").update(
                {"owner_name": collected["owner_name"]}
            ).eq("id", user_id).execute()
            user_flags["_owner_name_saved"] = True
            update_user_flags(user_id, user_flags)
        except Exception as e:
            logger.error("[ONB stream] owner_name save: %s", e)

    # 10. Completion — deterministic
    if current_step == "complete":
        create_result = _create_pet(user_id, collected)
        if create_result:
            pet_id, short_id = create_result
            user_flags["onboarding_collected"] = None
            user_flags["onboarding_pet_id"] = pet_id
            user_flags["onboarding_complete"] = True
            update_user_flags(user_id, user_flags)
            pet_card = None
            ai_text = _build_completion_text(collected)
            _save_ai_message(user_id, ai_text, pet_id, user_chat_id)
            return {"type": "final", "response": {
                "ai_response": ai_text, "quick_replies": [{"label": "Познакомиться с приложением", "value": "WALKTHROUGH", "preferred": True}],
                "onboarding_phase": "complete", "pet_id": pet_id,
                "pet_card": pet_card, "input_type": "text",
                "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
            }}

    # DatePicker — deterministic
    if current_step == "birth_date" and collected.get("_wants_date_picker"):
        return {"type": "final", "response": {
            "ai_response": "", "quick_replies": [],
            "onboarding_phase": "collecting", "pet_id": None, "pet_card": None,
            "input_type": "date_picker",
            "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
        }}

    # 11-13. Prepare prompt for LLM
    quick_replies = _get_step_quick_replies(current_step, collected, client)
    step_instruction = _get_step_instruction(current_step, collected)
    system_prompt = _build_system_prompt(collected, step_instruction, current_step, quick_replies)

    history_rows = _load_chat_history(user_id, limit=20)
    oai_messages = [{"role": "system", "content": system_prompt}]
    for row in history_rows:
        role = "assistant" if row["role"] == "ai" else "user"
        content = row.get("message") or ""
        if content:
            oai_messages.append({"role": role, "content": content})
    oai_messages.append({"role": "user", "content": actual_message or "Начни онбординг"})

    input_type = "date_picker" if (current_step == "birth_date" and collected.get("_wants_date_picker")) else "text"

    metadata = {
        "quick_replies": quick_replies,
        "onboarding_phase": "collecting",
        "pet_id": None,
        "pet_card": None,
        "input_type": input_type,
        "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
    }

    return {
        "type": "llm",
        "oai_messages": oai_messages,
        "metadata": metadata,
        "user_chat_id": user_chat_id,
        "user_id": user_id,
        "current_step": current_step,
        "collected_full": collected,
    }
