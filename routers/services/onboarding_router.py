"""
onboarding_router.py — Onboarding flow logic v5.
Two-stage onboarding, back intent, passport support, cat auto-gender.
"""

from routers.services.ai import _call_llm
from routers.services.model_router import get_model_for_response
from routers.services.memory import (
    get_owner_name, save_owner_name,
    get_onboarding_status, update_pet_profile,
    get_pet_profile, update_user_flags,
)
from routers.services.onboarding import (
    get_onboarding_message, validate_onboarding_input, is_off_topic,
    get_previous_step, OWNER_NAME_BLACKLIST, STAGE_2_STEPS,
)


def is_back_intent(message: str) -> bool:
    """
    Determine if user wants to go back / undo / correct input.
    Uses AI classification — NOT a keyword list.
    """
    _msg = message.strip().lower()

    # Quick keyword shortcut for obvious cases
    if _msg in ("назад", "back", "отмена", "стоп", "вернись", "undo"):
        return True

    # Short messages that are likely just answers, not back-intent
    if len(_msg) <= 3:
        return False

    try:
        _config = get_model_for_response(mode="ONBOARDING")
        result = _call_llm(
            config=_config,
            system_prompt=(
                "Ты классификатор намерений. Определи: пользователь хочет вернуться "
                "на предыдущий шаг / отменить / исправить ввод?\n"
                "Ответь ТОЛЬКО 'yes' или 'no'.\n"
                "Примеры yes: назад, нет подожди, ошибся, блин не то, упс, хочу изменить, "
                "стоп, отмена, вернись, подожди, back, wait, mistake, wrong\n"
                "Примеры no: любой ответ по существу вопроса"
            ),
            user_prompt=message,
            max_tokens=8,
        )
        return result.strip().lower() == "yes"
    except Exception:
        return False


def _field_to_step(field: str, pet_profile: dict) -> str:
    """Map field from get_onboarding_status() to onboarding.py step."""
    _map = {
        "species": "species",
        "name": "name",
        "gender": "gender",
        "neutered": "neutered",
        "age": "birth_date",
        "breed": "breed",
        "color": "color",
        "features": "features",
        "chip_id": "chip_id_ask",
        "stamp_id": "stamp_id_ask",
    }
    return _map.get(field, field)


def _error_result(step, phase, next_q, owner_name, msg="Не удалось сохранить данные, попробуй ещё раз."):
    """Return dict that keeps user on the same onboarding step after a DB error."""
    _ob_msg = get_onboarding_message(step, {}) if step else {}
    return {
        "message_mode": "ONBOARDING",
        "next_question": next_q,
        "owner_name": owner_name,
        "onboarding_phase": phase,
        "onboarding_step": step,
        "auto_follow": None,
        "quick_replies": _ob_msg.get("quick_replies", []) if _ob_msg else [],
        "input_type": _ob_msg.get("input_type", "text") if _ob_msg else "text",
        "validation": None,
        "is_off_topic": False,
        "onboarding_deterministic": True,
        "ai_response_override": msg,
        "pet_profile_updated": None,
        "chat_history": [],
    }


def _get_next_stage2_step(pet_profile: dict) -> str | None:
    """Find the next unfilled step in stage 2."""
    for step in STAGE_2_STEPS:
        field = step
        if step == "birth_date":
            if pet_profile.get("birth_date") or pet_profile.get("age_years") or pet_profile.get("birth_date_skipped"):
                continue
        elif step == "gender":
            if pet_profile.get("gender"):
                continue
        elif step == "neutered":
            if pet_profile.get("neutered") is not None or pet_profile.get("neutered_skipped"):
                continue
        elif step == "breed":
            if pet_profile.get("breed") or pet_profile.get("breed_skipped"):
                continue
        elif step == "color":
            if pet_profile.get("color") or pet_profile.get("color_skipped"):
                continue
        elif step == "features":
            if pet_profile.get("features") or pet_profile.get("features_skipped"):
                continue
        elif step == "photo_avatar":
            if pet_profile.get("avatar_url") or pet_profile.get("photo_avatar_skipped"):
                continue
        else:
            continue
        return step
    return None


def handle_onboarding(
    message_text: str,
    user_id: str,
    pet_id: str,
    pet_profile: dict,
    structured_data: dict,
    message_mode: str,
    supabase_client,
) -> dict:
    _message_mode = message_mode
    _next_question = None
    _owner_name = None
    _onboarding_phase = None
    _onboarding_step = None
    _auto_follow = None
    _quick_replies = []
    _input_type = "text"
    _is_off_topic = False
    _validation = None
    _onboarding_deterministic = False
    _ai_response_override = None
    _pet_profile_updated = None
    _chat_history = []

    # ── OWNER NAME CHECK (BEFORE pet onboarding) ──────────────────
    _owner_name = get_owner_name(user_id=user_id)

    if not _owner_name and _message_mode != "CLINICAL":
        # Check if we already asked (any AI message exists)
        _prior_ai_check = supabase_client.table("chat").select("id").eq("user_id", user_id).eq("role", "ai").limit(1).execute()
        _already_asked = bool(_prior_ai_check.data)

        if _already_asked:
            # Try to extract name from current message
            _raw = message_text.strip()
            _name_blacklist = [
                "привет", "здравствуйте", "здравствуй", "добрый", "доброе",
                "добрый день", "добрый вечер", "доброе утро", "хай", "hello",
                "hi", "здрасте", "хеллоу", "ку", "йо", "даров", "дратути",
            ]
            if (
                len(_raw) >= 2
                and len(_raw) <= 40
                and _raw.replace(" ", "").replace("-", "").isalpha()
                and _raw.lower() not in _name_blacklist
                and _raw.lower() not in OWNER_NAME_BLACKLIST
            ):
                save_owner_name(user_id=user_id, name=_raw.capitalize())
                _owner_name = _raw.capitalize()
            elif _raw.lower() in OWNER_NAME_BLACKLIST:
                # User typed a blacklisted word instead of name
                _message_mode = "ONBOARDING"
                _next_question = "owner_name"
                _onboarding_phase = "owner"
                _onboarding_deterministic = True
                _ai_response_override = "Напиши своё имя, например: Марк"
                _quick_replies = []
                _input_type = "text"
                return {
                    "message_mode": _message_mode,
                    "next_question": _next_question,
                    "owner_name": _owner_name,
                    "onboarding_phase": _onboarding_phase,
                    "onboarding_step": "owner_name",
                    "auto_follow": None,
                    "quick_replies": _quick_replies,
                    "input_type": _input_type,
                    "validation": None,
                    "is_off_topic": False,
                    "onboarding_deterministic": True,
                    "ai_response_override": _ai_response_override,
                    "pet_profile_updated": None,
                    "chat_history": [],
                }

        if not _owner_name:
            _message_mode = "ONBOARDING"
            _next_question = "owner_name"
            _onboarding_phase = "owner"

    # ── ONBOARDING override — only if no clinical symptom ─────────
    if _next_question != "owner_name":
        _saved_step = pet_profile.get("onboarding_step") if pet_profile else None
        _onboarding = get_onboarding_status(pet_id=pet_id)
        _onboarding_phase = _onboarding.get("phase")

        if not _onboarding["complete"] and _message_mode != "CLINICAL":
            _message_mode = "ONBOARDING"
            _next_question = _onboarding["next_question"]

            # Determine current step
            if _saved_step:
                _onboarding_step = _saved_step
            else:
                # Exception #1: skip species if already set
                if _next_question == "species" and pet_profile and pet_profile.get("species"):
                    # Species already known, move to name
                    _onboarding_step = "name"
                    _next_question = "name"
                # Between required and optional — show done_stage1 gate
                elif _onboarding_phase == "optional" and _next_question in ["breed", "color", "features", "chip_id", "stamp_id"]:
                    _gate_passed = _saved_step in STAGE_2_STEPS or (pet_profile or {}).get("optional_gate_passed")
                    if not _gate_passed:
                        _onboarding_step = "done_stage1"
                    else:
                        _onboarding_step = _field_to_step(_next_question, pet_profile or {})
                else:
                    _onboarding_step = _field_to_step(_next_question, pet_profile or {})

    # ── Process onboarding answer ─────────────────────────────────
    if _message_mode == "ONBOARDING" and _onboarding_step and _onboarding_step != "owner_name":

        # Check off-topic first
        _is_off_topic = is_off_topic(_onboarding_step, message_text)

        if _is_off_topic:
            try:
                _hist_result = (
                    supabase_client.table("chat")
                    .select("role, message")
                    .eq("pet_id", pet_id)
                    .order("created_at", desc=True)
                    .limit(20)
                    .execute()
                )
                if _hist_result.data:
                    _chat_history = list(reversed(_hist_result.data))
            except Exception as _hist_err:
                print(f"[chat_history] {_hist_err}")

        elif not _is_off_topic:
            # Check back intent BEFORE validation
            if is_back_intent(message_text):
                _prev_step = get_previous_step(_onboarding_step, pet_profile or {})
                if _prev_step:
                    _onboarding_step = _prev_step
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": _prev_step})
                    except Exception:
                        pass
                    # Return the previous step's message
                    _ob_msg = get_onboarding_message(_prev_step, pet_profile or {})
                    _onboarding_deterministic = True
                    _ai_response_override = _ob_msg["text"]
                    _quick_replies = _ob_msg.get("quick_replies", [])
                    _input_type = _ob_msg.get("input_type", "text")

                    return {
                        "message_mode": _message_mode,
                        "next_question": _next_question,
                        "owner_name": _owner_name,
                        "onboarding_phase": _onboarding_phase,
                        "onboarding_step": _prev_step,
                        "auto_follow": None,
                        "quick_replies": _quick_replies,
                        "input_type": _input_type,
                        "validation": None,
                        "is_off_topic": False,
                        "onboarding_deterministic": True,
                        "ai_response_override": _ai_response_override,
                        "pet_profile_updated": None,
                        "chat_history": [],
                    }

            # Validate user's answer
            _validation = validate_onboarding_input(
                step=_onboarding_step,
                user_message=message_text,
                pet_profile=pet_profile or {}
            )

            if _validation["valid"]:
                # Save parsed fields
                if _validation.get("field_updates"):
                    try:
                        update_pet_profile(pet_id=pet_id, fields=_validation["field_updates"])
                        pet_profile = get_pet_profile(pet_id=pet_id)
                        _pet_profile_updated = pet_profile
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile failed: {e}")
                        return _error_result(_onboarding_step, _onboarding_phase, _next_question, _owner_name)

                # Save pet_count to users table
                if _onboarding_step == "pet_count" and _validation.get("field_updates", {}).get("pet_count"):
                    try:
                        supabase_client.table("users").update(
                            {"pet_count": _validation["field_updates"]["pet_count"]}
                        ).eq("id", user_id).execute()
                    except Exception:
                        pass

                _next_step = _validation.get("next_step")

                if _next_step == "complete":
                    # Onboarding complete
                    _message_mode = "ONBOARDING_COMPLETE"
                    _onboarding_step = None
                    _next_question = None
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": None})
                    except Exception:
                        pass

                elif _next_step == "stage2":
                    # Move to stage 2
                    _next_s2 = _get_next_stage2_step(pet_profile or {})
                    if _next_s2:
                        _onboarding_step = _next_s2
                        _next_question = _next_s2
                        try:
                            update_pet_profile(pet_id=pet_id, fields={"onboarding_step": _next_s2, "optional_gate_passed": True})
                        except Exception:
                            pass
                    else:
                        # All stage 2 fields already filled
                        _message_mode = "ONBOARDING_COMPLETE"
                        _onboarding_step = None
                        _next_question = None

                elif _next_step:
                    # Explicit branching
                    _onboarding_step = _next_step
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": _next_step})
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile next_step failed: {e}")
                        return _error_result(_onboarding_step, _onboarding_phase, _next_question, _owner_name)

                elif _onboarding_step == "name":
                    # Exception #3: after name → name_reaction_and_gender for dogs, skip for cats
                    _species = (pet_profile or {}).get("species", "")
                    _gender = (pet_profile or {}).get("gender")

                    if _species == "dog" or (_species != "cat" and not _gender):
                        # Dog: combined reaction + gender question
                        _onboarding_step = "name_reaction_and_gender"
                        try:
                            update_pet_profile(pet_id=pet_id, fields={"onboarding_step": "name_reaction_and_gender"})
                        except Exception:
                            pass
                    else:
                        # Cat: gender already set from species, go to passport_entry
                        _onboarding_step = "passport_entry"
                        try:
                            update_pet_profile(pet_id=pet_id, fields={"onboarding_step": "passport_entry"})
                        except Exception:
                            pass

                elif _onboarding_step == "name_reaction_and_gender":
                    # Gender answered after name reaction → go to passport_entry
                    _onboarding_step = "passport_entry"
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": "passport_entry"})
                    except Exception:
                        pass

                elif _onboarding_step == "species":
                    # Exception #2: if cat with auto-gender, skip to name
                    _gender = (pet_profile or {}).get("gender")
                    _onboarding_step = "name"
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": "name"})
                    except Exception:
                        pass

                elif _onboarding_step == "pet_count":
                    # After pet_count → species (or skip if already set)
                    _species = (pet_profile or {}).get("species")
                    if _species:
                        _onboarding_step = "name"
                    else:
                        _onboarding_step = "species"
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": _onboarding_step})
                    except Exception:
                        pass

                else:
                    # Standard transition: recheck status
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": None})
                    except Exception:
                        pass

                    # In stage 2: find next unfilled step
                    if _onboarding_step in STAGE_2_STEPS:
                        _next_s2 = _get_next_stage2_step(pet_profile or {})
                        if _next_s2:
                            _onboarding_step = _next_s2
                            _next_question = _next_s2
                            try:
                                update_pet_profile(pet_id=pet_id, fields={"onboarding_step": _next_s2})
                            except Exception:
                                pass
                        else:
                            _message_mode = "ONBOARDING_COMPLETE"
                            _onboarding_step = None
                            _next_question = None
                    else:
                        _onboarding_recheck = get_onboarding_status(pet_id=pet_id)
                        _onboarding_phase = _onboarding_recheck.get("phase")

                        if _onboarding_recheck["complete"]:
                            _message_mode = "ONBOARDING_COMPLETE"
                            _onboarding_step = None
                            _next_question = None
                        else:
                            _next_field = _onboarding_recheck["next_question"]
                            if _onboarding_recheck["phase"] == "optional":
                                _gate_passed = (pet_profile or {}).get("optional_gate_passed")
                                if not _gate_passed:
                                    _onboarding_step = "done_stage1"
                                else:
                                    _onboarding_step = _field_to_step(_next_field, pet_profile or {})
                            else:
                                _onboarding_step = _field_to_step(_next_field, pet_profile or {})
                            _next_question = _next_field

    print(f"[ONBOARDING DEBUG] mode={_message_mode} step={_onboarding_step} next_q={_next_question} off_topic={_is_off_topic}")

    # ── Deterministic response generation ─────────────────────────
    _onboarding_deterministic = False

    if _message_mode == "ONBOARDING" and _onboarding_step and _onboarding_step != "owner_name" and not _is_off_topic:
        _onboarding_deterministic = True

        if _validation is not None and not _validation.get("valid", True):
            # Validation error
            _ai_response_override = _validation.get("error_message", "Не совсем понял. Попробуй ещё раз.")
            _ob_msg = get_onboarding_message(_onboarding_step, pet_profile or {})
            _quick_replies = _ob_msg.get("quick_replies", [])
            _input_type = _ob_msg.get("input_type", "text")

        elif _message_mode == "ONBOARDING_COMPLETE":
            _onboarding_deterministic = False

        else:
            # Standard step — deterministic message
            _ob_msg = get_onboarding_message(_onboarding_step, pet_profile or {})
            _ai_response_override = _ob_msg["text"]
            _quick_replies = _ob_msg.get("quick_replies", [])
            _input_type = _ob_msg.get("input_type", "text")

    # After off-topic: add quick_replies for current step
    if _is_off_topic and _onboarding_step:
        _ob_current = get_onboarding_message(_onboarding_step, pet_profile or {})
        _quick_replies = _ob_current.get("quick_replies", [])
        _input_type = _ob_current.get("input_type", "text")

    return {
        "message_mode": _message_mode,
        "next_question": _next_question,
        "owner_name": _owner_name,
        "onboarding_phase": _onboarding_phase,
        "onboarding_step": _onboarding_step,
        "auto_follow": _auto_follow,
        "quick_replies": _quick_replies,
        "input_type": _input_type,
        "validation": _validation,
        "is_off_topic": _is_off_topic,
        "onboarding_deterministic": _onboarding_deterministic,
        "ai_response_override": _ai_response_override,
        "pet_profile_updated": _pet_profile_updated,
        "chat_history": _chat_history,
    }
