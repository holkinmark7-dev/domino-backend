"""
onboarding_router.py — Onboarding flow logic extracted from routers/chat.py.
Handles owner name check, onboarding step detection, validation, transitions,
deterministic response generation, and off-topic detection.
"""

from routers.services.memory import (
    get_owner_name, save_owner_name,
    get_onboarding_status, update_pet_profile,
    get_pet_profile, update_user_flags,
)
from routers.services.onboarding import (
    get_onboarding_message, validate_onboarding_input, is_off_topic,
)


def _field_to_step(field: str, pet_profile: dict) -> str:
    """
    Map field from get_onboarding_status() to onboarding.py step.
    For fields with branching, returns the first step of the branch.
    """
    _map = {
        "species": "species",
        "name": "name",
        "gender": "gender",
        "neutered": "neutered",
        "age": "age_choice",
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

    # ── OWNER NAME CHECK (ДО онбординга питомца) ─────────────────────
    if _message_mode != "REGISTRATION_PROMPT":
        _owner_name = get_owner_name(user_id=user_id)

        if not _owner_name and _message_mode != "CLINICAL":
            # Проверяем есть ли предыдущие AI-сообщения (уже спрашивали имя?)
            _prior_ai_check = supabase_client.table("chat").select("id").eq("user_id", user_id).eq("role", "ai").limit(1).execute()
            _already_asked = bool(_prior_ai_check.data)

            if _already_asked:
                # Пробуем распознать имя из текущего сообщения
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
                ):
                    save_owner_name(user_id=user_id, name=_raw.capitalize())
                    _owner_name = _raw.capitalize()

            if not _owner_name:
                # Имя ещё не получено — спрашиваем
                _message_mode = "ONBOARDING"
                _next_question = "owner_name"
                _onboarding_phase = "owner"

    # ── ONBOARDING override — только если нет симптома и профиль не заполнен
    if _next_question != "owner_name" and _message_mode != "REGISTRATION_PROMPT":
        # Проверяем сохранённый под-шаг (для ветвлений: age_date, chip_id_input, итд)
        _saved_step = pet_profile.get("onboarding_step") if pet_profile else None

        _onboarding = get_onboarding_status(pet_id=pet_id)
        _onboarding_phase = _onboarding.get("phase")

        if not _onboarding["complete"] and _message_mode != "CLINICAL":
            _message_mode = "ONBOARDING"
            _next_question = _onboarding["next_question"]

            # Определяем текущий шаг: сохранённый под-шаг или маппинг из поля
            if _saved_step:
                _onboarding_step = _saved_step
            else:
                # Между required и optional — показать optional_gate
                if _onboarding_phase == "optional" and _next_question in ["breed", "color", "features", "chip_id", "stamp_id"]:
                    # Определяем программно: если saved_step на optional шаге → gate пройден
                    _gate_passed = _saved_step in ["breed", "color", "features", "chip_id_ask", "chip_id_input", "stamp_id_ask", "stamp_id_input"]
                    if not _gate_passed:
                        _onboarding_step = "optional_gate"
                    else:
                        _onboarding_step = _field_to_step(_next_question, pet_profile or {})
                else:
                    _onboarding_step = _field_to_step(_next_question, pet_profile or {})

    # ── Обработка ответа онбординга (детерминированный движок) ──
    if _message_mode == "ONBOARDING" and _onboarding_step and _onboarding_step != "owner_name":

        # Проверяем off-topic
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

        if not _is_off_topic:
            # Валидируем ответ пользователя
            _validation = validate_onboarding_input(
                step=_onboarding_step,
                user_message=message_text,
                pet_profile=pet_profile or {}
            )

            if _validation["valid"]:
                # Сохраняем распарсенные поля
                if _validation.get("field_updates"):
                    try:
                        update_pet_profile(pet_id=pet_id, fields=_validation["field_updates"])
                        pet_profile = get_pet_profile(pet_id=pet_id)
                        _pet_profile_updated = pet_profile
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile failed: {e}")
                        return _error_result(_onboarding_step, _onboarding_phase, _next_question, _owner_name)

                # optional_gate: запоминаем что прошли
                _next_step = _validation.get("next_step")
                if _onboarding_step == "optional_gate" and _next_step and _next_step != "complete":
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"optional_gate_passed": True})
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile optional_gate failed: {e}")
                        return _error_result(_onboarding_step, _onboarding_phase, _next_question, _owner_name)

                if _next_step == "complete":
                    # Онбординг завершён
                    _message_mode = "ONBOARDING_COMPLETE"
                    _onboarding_step = None
                    _next_question = None
                    # Очищаем onboarding_step в БД
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": None})
                        update_user_flags(user_id=user_id, flags={"show_registration_prompt": True})
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile complete failed: {e}")

                elif _next_step:
                    # Явное ветвление (age_choice → age_date/age_approx, итд)
                    _onboarding_step = _next_step
                    # Сохраняем под-шаг в БД
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": _next_step})
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile next_step failed: {e}")
                        return _error_result(_onboarding_step, _onboarding_phase, _next_question, _owner_name)

                elif _onboarding_step == "name":
                    # После имени → name_reaction + auto_follow gender
                    _onboarding_step = "name_reaction"
                    # НЕ сохраняем name_reaction как шаг — он транзитный
                    # Следующий реальный шаг — gender
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": "gender"})
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile name→gender failed: {e}")
                        return _error_result(_onboarding_step, _onboarding_phase, _next_question, _owner_name)

                else:
                    # Стандартный переход: перепроверяем статус
                    # Очищаем сохранённый под-шаг
                    try:
                        update_pet_profile(pet_id=pet_id, fields={"onboarding_step": None})
                    except Exception as e:
                        print(f"[onboarding] update_pet_profile clear step failed: {e}")
                        return _error_result(_onboarding_step, _onboarding_phase, _next_question, _owner_name)
                    _onboarding_recheck = get_onboarding_status(pet_id=pet_id)
                    _onboarding_phase = _onboarding_recheck.get("phase")

                    if _onboarding_recheck["complete"]:
                        _message_mode = "ONBOARDING_COMPLETE"
                        _onboarding_step = None
                        _next_question = None
                        update_user_flags(user_id=user_id, flags={"show_registration_prompt": True})
                    else:
                        _next_field = _onboarding_recheck["next_question"]
                        # Проверяем optional_gate
                        if _onboarding_recheck["phase"] == "optional":
                            _saved_step_recheck = (pet_profile or {}).get("onboarding_step")
                            _gate_passed_recheck = _saved_step_recheck in [
                                "breed", "color", "features",
                                "chip_id_ask", "chip_id_input", "stamp_id_ask", "stamp_id_input",
                            ]
                            if not _gate_passed_recheck and not (pet_profile or {}).get("optional_gate_passed"):
                                _onboarding_step = "optional_gate"
                            else:
                                _onboarding_step = _field_to_step(_next_field, pet_profile or {})
                        else:
                            _onboarding_step = _field_to_step(_next_field, pet_profile or {})
                        _next_question = _next_field

            else:
                # Невалидный ввод — остаёмся на том же шаге, показываем ошибку
                # _onboarding_step не меняется
                pass

    print(f"[ONBOARDING DEBUG] mode={_message_mode} step={_onboarding_step} next_q={_next_question} off_topic={_is_off_topic} deterministic={_onboarding_deterministic}")

    # ── Детерминированный ответ онбординга ──
    _onboarding_deterministic = False

    if _message_mode == "ONBOARDING" and _onboarding_step and _onboarding_step != "owner_name" and not _is_off_topic:
        _onboarding_deterministic = True

        # Проверяем: была ли ошибка валидации?
        if _validation is not None and not _validation.get("valid", True):
            # Ошибка — показываем error_message
            _ai_response_override = _validation.get("error_message", "Не совсем понял. Попробуй ещё раз.")
            _ob_msg = get_onboarding_message(_onboarding_step, pet_profile or {})
            _quick_replies = _ob_msg.get("quick_replies", [])
            _input_type = _ob_msg.get("input_type", "text")

        elif _message_mode == "ONBOARDING_COMPLETE":
            # Завершение — пойдёт через LLM (ONBOARDING_COMPLETE mode)
            _onboarding_deterministic = False

        elif _onboarding_step == "name_reaction":
            # name_reaction + auto_follow gender
            _ob_reaction = get_onboarding_message("name_reaction", pet_profile or {})
            _ai_response_override = _ob_reaction["text"]
            _quick_replies = []
            _input_type = "none"

            # auto_follow — gender вопрос через 1 сек
            _ob_gender = get_onboarding_message("gender", pet_profile or {})
            _auto_follow = {
                "text": _ob_gender["text"],
                "quick_replies": _ob_gender.get("quick_replies", []),
                "input_type": _ob_gender.get("input_type", "buttons"),
                "delay_ms": 1000,
                "onboarding_field": "gender",
            }

        else:
            # Стандартный шаг — детерминированная строка
            _ob_msg = get_onboarding_message(_onboarding_step, pet_profile or {})
            _ai_response_override = _ob_msg["text"]
            _quick_replies = _ob_msg.get("quick_replies", [])
            _input_type = _ob_msg.get("input_type", "text")

    # После off-topic: добавляем quick_replies текущего шага чтобы фронт показал кнопки
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
