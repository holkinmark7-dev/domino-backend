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

    # 2b. Breed detection
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
                # Несколько вариантов — показываем пользователю, early return
                ai_text = "Вижу несколько вариантов по фото."
                breed_qr = [
                    {
                        "label": f"{b['name_ru']} ({int(b['probability'] * 100)}%)",
                        "value": b["name_ru"],
                        "preferred": i == 0,
                    }
                    for i, b in enumerate(breeds[:3])
                ]
                breed_qr.append({"label": "Другая порода", "value": "Другая порода", "preferred": False})

                # Save state before early return
                user_chat_id = _save_user_message(user_id, "Фото для определения породы")
                user_flags["onboarding_collected"] = collected
                update_user_flags(user_id, user_flags)
                _save_ai_message(user_id, ai_text, None, user_chat_id)

                logger.warning("[ONB] === SENDING TO FRONT === qr_count=%d qr_labels=%s input_type=%s ai_text_len=%d phase=%s",
                               len(breed_qr) if isinstance(breed_qr, list) else 0,
                               [q["label"] for q in breed_qr][:5] if isinstance(breed_qr, list) else [],
                               "text",
                               len(ai_text) if ai_text else 0,
                               "collecting")
                return JSONResponse(content={
                    "ai_response": ai_text,
                    "quick_replies": breed_qr,
                    "onboarding_phase": "collecting",
                    "pet_id": None,
                    "pet_card": None,
                    "input_type": "text",
                    "collected": {k: v for k, v in collected.items() if not k.startswith("_")},
                })
        else:
            actual_message = "Не удалось определить породу по фото."

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

    # 12. Compute step instruction
    step_instruction = _get_step_instruction(current_step, collected)
    original_step_instruction = step_instruction

    # --- Placeholder для поля ввода ---
    _STEP_PLACEHOLDERS = {
        "owner_name": "Твоё имя",
        "pet_name": "Например: Бобик, Мурка, Рекс",
        "breed": "Порода питомца",
        "birth_date": "ДД.ММ.ГГГГ",
    }
    placeholder = _STEP_PLACEHOLDERS.get(current_step, "Написать...")

    # --- Определяем режим ---
    # [QUESTION] = AI пишет реакцию, вопрос из кода
    # "Скажи РОВНО" = точный текст, без AI свободы
    # Остальное = AI пишет всё (ЦЕЛЬ)
    question = None
    reaction_instruction = ""
    if "[QUESTION]" in step_instruction:
        parts = step_instruction.split("[QUESTION]")
        reaction_instruction = parts[0].strip()
        question = parts[1].strip()
        step_instruction = reaction_instruction  # AI получит только реакцию

    is_exact = step_instruction.startswith("Скажи РОВНО")

    # 13. Build system prompt
    system_prompt = _build_system_prompt(
        collected, step_instruction, current_step, quick_replies, question=question
    )

    # 14. Call Claude Haiku
    def _fix_anthropic_messages(messages):
        """Anthropic requires alternating user/assistant roles."""
        if not messages:
            return [{"role": "user", "content": "Начни онбординг"}]
        fixed = []
        for msg in messages:
            if fixed and fixed[-1]["role"] == msg["role"]:
                fixed[-1]["content"] += "\n" + msg["content"]
            else:
                fixed.append(msg)
        if fixed and fixed[0]["role"] == "assistant":
            fixed.insert(0, {"role": "user", "content": "..."})
        return fixed

    # Few-shot: эталонный диалог Dominik — AI копирует стиль
    _FEW_SHOT_MESSAGES = [
        {"role": "user", "content": "Ну Марк"},
        {"role": "assistant", "content": "Марк, расскажи — кто у тебя?"},
        {"role": "user", "content": "У меня собака, подобрал на улице"},
        {"role": "assistant", "content": "Подобрал — значит друг другу повезло. Как зовут?"},
        {"role": "user", "content": "Бобик"},
        {"role": "assistant", "content": "Бобик — с таким точно не заскучаешь. Зачем пришёл — что-то беспокоит или просто на контроль?"},
        {"role": "user", "content": "Овчарка"},
        {"role": "assistant", "content": "Овчарок много — немецкая, кавказская? Уточни."},
        {"role": "user", "content": "Кавказская"},
        {"role": "assistant", "content": "Кавказец — серьёзный зверь, уважаю. Когда родился Бобик?"},
        {"role": "user", "content": "Примерно 5 лет"},
        {"role": "assistant", "content": "Пять лет — самый расцвет. Мальчик или девочка?"},
    ]

    try:
        ant_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

        if is_exact:
            # Точный текст — без истории, temp 0
            ant_messages = [
                {"role": "user", "content": actual_message or "Начни онбординг"},
            ]
            resp = ant_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system=system_prompt,
                messages=ant_messages,
                temperature=0.0,
            )
            ai_text = resp.content[0].text.strip()

        elif question and not reaction_instruction:
            # Только вопрос, без реакции (species, passport, is_neutered, avatar)
            ai_text = question

        elif question and reaction_instruction:
            # Реакция от AI + вопрос из кода (goal, breed, birth_date, gender)
            history_rows = _load_chat_history(user_id, limit=10)
            ant_messages = []
            ant_messages.extend(_FEW_SHOT_MESSAGES)
            for row in history_rows:
                role = "assistant" if row["role"] == "ai" else "user"
                content = row.get("message") or ""
                if content:
                    ant_messages.append({"role": role, "content": content})
            ant_messages.append({"role": "user", "content": actual_message or "Продолжай"})
            ant_messages = _fix_anthropic_messages(ant_messages)

            resp = ant_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=80,
                system=system_prompt,
                messages=ant_messages,
                temperature=0.5,
            )
            reaction = resp.content[0].text.strip()
            reaction = _remove_stop_phrases(reaction)

            # Убираем вопросы из реакции — AI мог добавить
            if "?" in reaction:
                reaction = reaction.split("?")[0].rstrip() + "."

            ai_text = f"{reaction}\n\n{question}"

        else:
            # Полная свобода (pet_name, owner_name переспрос)
            history_rows = _load_chat_history(user_id, limit=20)
            ant_messages = []
            ant_messages.extend(_FEW_SHOT_MESSAGES)
            for row in history_rows:
                role = "assistant" if row["role"] == "ai" else "user"
                content = row.get("message") or ""
                if content:
                    ant_messages.append({"role": role, "content": content})
            ant_messages.append({"role": "user", "content": actual_message or "Начни онбординг"})
            ant_messages = _fix_anthropic_messages(ant_messages)

            resp = ant_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system=system_prompt,
                messages=ant_messages,
                temperature=0.5,
            )
            ai_text = resp.content[0].text.strip()

        # Пост-обработка (кроме reaction+question — уже обработано)
        if not (question and reaction_instruction):
            ai_text = _remove_stop_phrases(ai_text)

        logger.warning("[ONB] === AI RESPONSE === text='%s'", ai_text[:100] if ai_text else "EMPTY")

    except Exception as e:
        logger.error("[haiku_call] %s", e)
        ai_text = ""

    # Уровень 3: keyword check — пропускается для ЦЕЛЬ и [QUESTION]
    if not step_instruction.startswith("ЦЕЛЬ:") and "[QUESTION]" not in original_step_instruction:
        _STEP_KEYWORDS = {
            "owner_name": ["зовут", "имя", "тебя"],
            "pet_name": ["зовут", "питом", "кличк"],
            "species_guess_dog": ["собак", "пёс", "пес", "угадал"],
            "species_guess_cat": ["кот", "угадал"],
            "species": ["кошк", "собак", "кот"],
            "passport_offer": ["паспорт", "сфотограф", "перенес"],
            "breed": ["поро", "какая", "уточн", "фото", "пиши", "загруз"],
            "birth_date": ["родил", "когда", "дат", "возраст", "сколько"],
            "gender": ["мальчик", "девочк", "пол"],
            "is_neutered": ["кастр", "стерил"],
            "avatar": ["фото", "профил", "последн", "штрих", "мордаш"],
        }

        keywords = _STEP_KEYWORDS.get(current_step, [])
        if keywords and ai_text:
            text_lower = ai_text.lower()
            has_keyword = any(kw in text_lower for kw in keywords)
            if not has_keyword:
                logger.warning("[ONB] AI text FAILED keyword check for step=%s, replacing with fallback. AI said: '%s'",
                              current_step, ai_text[:80])
                ai_text = _get_fallback_text(current_step, collected)

    # 15. Fallback if empty response
    if not ai_text:
        ai_text = _get_fallback_text(current_step, collected)

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
