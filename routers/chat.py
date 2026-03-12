from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from dependencies.auth import get_current_user
from dependencies.limiter import limiter
from schemas.chat import ChatMessage
from routers.services.memory import (
    save_event,
    save_medical_event,
    get_recent_events,
    get_pet_profile,
    get_medical_events,
    ensure_user_exists,
    get_user_flags,
    update_user_flags,
)
from routers.services.ai import generate_ai_response, extract_event_data, AIResponseRequest
from routers.services.symptom_registry import normalize_symptom
from routers.services.symptom_class_registry import get_symptom_class
from routers.services.episode_manager import process_event, update_episode_escalation
from routers.onboarding_ai import handle_onboarding_ai
from routers.services.clinical_router import build_full_clinical_decision
from routers.services.decision_postprocess import postprocess_decision
from routers.services.chat_helpers import (
    strip_markdown_json,
    compute_age_years,
    count_questions,
    build_missing_facts,
    _classify_message_mode,
)
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
import json
import time
from datetime import datetime, timezone, timedelta, date
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

GREETING_COOLDOWN_HOURS = 5


def _update_last_seen(user_id: str):
    """Update last_seen timestamp for the user."""
    try:
        supabase.table("users").update(
            {"last_seen": datetime.now(timezone.utc).isoformat()}
        ).eq("id", user_id).execute()
    except Exception as e:
        logger.warning("[last_seen] update failed: %s", e)


def _should_greet(user_id: str) -> bool:
    """Check if enough time has passed since last_seen (>5 hours)."""
    try:
        result = (
            supabase.table("users")
            .select("last_seen")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return True
        last_seen = result.data[0].get("last_seen")
        if not last_seen:
            return True
        last_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - last_dt) > timedelta(hours=GREETING_COOLDOWN_HOURS)
    except Exception as e:
        logger.warning("[should_greet] check failed: %s", e)
        return False


def _get_greeting(client_time: str | None) -> str:
    """Return time-of-day greeting based on client_time or server UTC+3."""
    hour = None
    if client_time:
        try:
            hour = int(client_time[:2])
        except (ValueError, IndexError):
            pass
    if hour is None:
        # fallback: server time UTC+3 (Moscow)
        hour = (datetime.now(timezone.utc) + timedelta(hours=3)).hour

    if 6 <= hour < 12:
        return "Доброе утро"
    elif 12 <= hour < 18:
        return "Добрый день"
    elif 18 <= hour < 24:
        return "Добрый вечер"
    else:
        return "Доброй ночи"


def _extract_and_normalize(message_text: str) -> dict:
    """
    Вызывает LLM extraction, нормализует симптом, применяет keyword overrides.
    Возвращает structured_data dict (с полями symptom, symptom_class и т.д.)
    или {"error": "..."} при ошибке.
    """
    try:
        raw_structured = extract_event_data(message_text)
        cleaned = strip_markdown_json(raw_structured)
        structured_data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("[extraction error] Failed to parse LLM response: %s", e)
        return {"error": "invalid_json"}
    except Exception as _ext_err:
        logger.error("[extraction error] OpenAI call failed: %s", _ext_err)
        return {"error": "extraction_failed"}

    # Symptom normalization
    if "error" not in structured_data:
        structured_data["symptom"] = normalize_symptom(structured_data.get("symptom"))
        structured_data["symptom_class"] = get_symptom_class(structured_data.get("symptom"))

    # Keyword override
    if "error" not in structured_data:
        _kw_msg = message_text.lower()
        _kw_override = None
        if "ксилит" in _kw_msg or "ксилитол" in _kw_msg:
            _kw_override = "xylitol_toxicity"
        elif "антифриз" in _kw_msg:
            _kw_override = "antifreeze"
        elif "крысиный яд" in _kw_msg or "отрава для крыс" in _kw_msg:
            _kw_override = "rodenticide"
        elif any(k in _kw_msg for k in ["чёрный стул", "дёгтеобразный стул", "чёрный кал"]):
            _kw_override = "melena"
        elif any(k in _kw_msg for k in ["кофейная гуща", "кофейной гущей", "рвёт кофейной", "рвота кофейной"]):
            _kw_override = "coffee_ground_vomit"
        elif any(k in _kw_msg for k in ["не ест", "отказывается от еды", "не хочет есть"]):
            _kw_override = "anorexia"
        elif any(k in _kw_msg for k in [
            "тужится", "не писает", "не может пописать", "не может помочиться",
            "мало мочи", "сидит в лотке", "часто ходит в лоток",
        ]):
            _kw_override = "urinary_obstruction"
        if _kw_override:
            structured_data["symptom"] = _kw_override
            structured_data["symptom_class"] = get_symptom_class(_kw_override)

    return structured_data


def _extract_vitals(structured_data: dict) -> dict:
    """
    Извлекает числовые витальные показатели из structured_data.
    Возвращает dict с ключами: lethargy_level, temperature_value,
    respiratory_rate, seizure_duration.
    """
    result = {
        "lethargy_level": "none",
        "temperature_value": None,
        "respiratory_rate": None,
        "seizure_duration": None,
    }
    if not isinstance(structured_data, dict) or "error" in structured_data:
        return result

    result["lethargy_level"] = structured_data.get("lethargy_level") or "none"

    _raw_temp = structured_data.get("temperature_value")
    if isinstance(_raw_temp, (int, float)):
        result["temperature_value"] = float(_raw_temp)
    elif isinstance(_raw_temp, str):
        try:
            result["temperature_value"] = float(_raw_temp)
        except (ValueError, TypeError):
            pass

    _rr_raw = structured_data.get("respiratory_rate")
    if isinstance(_rr_raw, (int, float)):
        result["respiratory_rate"] = int(_rr_raw)

    _sd_raw = structured_data.get("seizure_duration")
    if isinstance(_sd_raw, (int, float)):
        result["seizure_duration"] = float(_sd_raw)

    return result


def _detect_red_flags(message_text: str) -> bool:
    """Проверяет наличие ключевых слов экстренных состояний."""
    _rf_text = message_text.lower()
    red_flag_keywords = [
        "судорог", "потерял сознание", "не дыш", "задыха",
        "кровотеч", "съел пакет", "проглотил", "инородн",
        "не вста", "паралич", "не моч", "лежит и не реаг", "не реаг",
    ]
    return any(kw in _rf_text for kw in red_flag_keywords)


def _build_memory_context(all_medical_events: list) -> tuple:
    """
    Строит текстовый memory_context и определяет temporal_flag.
    Возвращает (memory_context: str, temporal_flag: str).
    """
    if not all_medical_events:
        return "No prior medical history.", "no_history"

    _mem_risk_map = {0: "normal", 1: "low", 2: "moderate", 3: "high"}
    _lines = []
    _last_valid_ts = None

    for _e in all_medical_events:
        _c = _e.get("content", {})
        if not isinstance(_c, dict) or "error" in _c:
            continue
        _date = (_e.get("created_at") or "")[:10]
        _symptom = _c.get("symptom") or _c.get("behavior") or "unknown"
        _raw_u = _c.get("urgency_score")
        _u = _raw_u if isinstance(_raw_u, int) and 0 <= _raw_u <= 3 else None
        _lines.append(f"- {_date}: {_symptom} ({_mem_risk_map.get(_u, 'unknown')})")
        if _last_valid_ts is None:
            _raw_ts = _e.get("created_at")
            if _raw_ts:
                try:
                    _last_valid_ts = datetime.fromisoformat(_raw_ts)
                except (ValueError, TypeError):
                    pass

    if _last_valid_ts is not None:
        _now = datetime.now(timezone.utc)
        if _last_valid_ts.tzinfo is None:
            _last_valid_ts = _last_valid_ts.replace(tzinfo=timezone.utc)
        _diff_minutes = (_now - _last_valid_ts).total_seconds() / 60
        if _diff_minutes <= 10:
            temporal_flag = "continuation"
        elif _diff_minutes <= 1440:
            temporal_flag = "recent_repeat"
        else:
            temporal_flag = "new_episode"
    else:
        temporal_flag = "no_history"

    if _lines:
        memory_context = "Previous medical history:\n" + "\n".join(_lines)
        memory_context += f"\nTemporal status: {temporal_flag}"
    else:
        memory_context = "No prior medical history."
        temporal_flag = "no_history"

    return memory_context, temporal_flag


def _compute_urgency(structured_data: dict, decision: dict) -> dict:
    """
    Вычисляет urgency_score, risk_level, sos, needs_followup и сообщения.
    Возвращает dict со всеми urgency-полями.
    """
    if "error" in structured_data:
        urgency_score = None
    else:
        raw_urgency = structured_data.get("urgency_score", 0)
        if isinstance(raw_urgency, int) and 0 <= raw_urgency <= 3:
            urgency_score = raw_urgency
        else:
            urgency_score = None

    if decision and decision.get("override_urgency") and isinstance(urgency_score, int):
        urgency_score = max(urgency_score, 3)

    risk_level_map = {0: "normal", 1: "low", 2: "moderate", 3: "high"}
    risk_level = risk_level_map.get(urgency_score, "unknown")
    sos = urgency_score == 3
    needs_followup = isinstance(urgency_score, int) and urgency_score >= 2

    if urgency_score == 3:
        escalation_message = "This situation may require urgent veterinary attention."
    elif urgency_score == 2:
        escalation_message = "Наблюдайте за питомцем и обратитесь к ветеринару если симптомы не проходят."
    else:
        escalation_message = None

    followup_instructions = (
        "Следите за дыханием, аппетитом и активностью в течение следующих 24 часов."
        if isinstance(urgency_score, int) and urgency_score >= 2
        else None
    )

    return {
        "urgency_score": urgency_score,
        "risk_level": risk_level,
        "sos": sos,
        "needs_followup": needs_followup,
        "escalation_message": escalation_message,
        "followup_instructions": followup_instructions,
    }


@router.post("/chat")
@limiter.limit("10/minute")
def create_chat_message(message: ChatMessage, request: Request = None, current_user: dict = Depends(get_current_user)):
    _t0 = time.perf_counter()

    if isinstance(current_user, dict) and message.user_id != current_user["id"]:
        return JSONResponse(status_code=403, content={"error": "Forbidden"})

    # Ownership check — skip during onboarding (no pet yet)
    if message.pet_id:
        _ownership = (
            supabase.table("pets")
            .select("id")
            .eq("id", message.pet_id)
            .eq("user_id", message.user_id)
            .limit(1)
            .execute()
        )
        if not _ownership.data:
            return JSONResponse(
                status_code=403,
                content={"error": "pet not found or access denied"}
            )

    ensure_user_exists(message.user_id)

    # ── Onboarding early return — no pet_id means AI-driven onboarding ──
    if not message.pet_id:
        _update_last_seen(message.user_id)
        return handle_onboarding_ai(
            user_id=message.user_id,
            message_text=message.message or "",
            passport_ocr_data=message.passport_ocr_data,
        )

    _update_last_seen(message.user_id)
    is_onboarding = False  # early return above handles onboarding

    # 1. Сохраняем сообщение
    chat_data_list = []
    if message.message and message.message.strip():
        chat_data = supabase.table("chat").insert({
            "user_id": message.user_id,
            "pet_id": message.pet_id,
            "message": message.message,
            "role": "user",
            "mode": "user",
        }).execute()
        chat_data_list = chat_data.data
        logger.debug("USER INSERT DATA: %s", chat_data_list)

        # 2. Сохраняем chat_message
        save_event(
            user_id=message.user_id,
            pet_id=message.pet_id,
            event_type="chat_message",
            content=message.message,
        )

    # 3. Extraction + normalization + keyword overrides
    structured_data = _extract_and_normalize(message.message)
    _t1_extraction = time.perf_counter()

    # Message mode classification — CASUAL / PROFILE / CLINICAL
    _message_mode = _classify_message_mode(structured_data, message.message)
    _next_question = None
    _owner_name = None
    _onboarding_phase = None

    # Early vitals extraction
    _vitals = _extract_vitals(structured_data)
    _lethargy_level = _vitals["lethargy_level"]
    _temperature_value = _vitals["temperature_value"]
    _respiratory_rate = _vitals["respiratory_rate"]
    _seizure_duration = _vitals["seizure_duration"]
    _respiratory_recalibrated = False

    # Pet profile — early fetch for species/age and vital rules
    pet_profile = get_pet_profile(pet_id=message.pet_id) or {}
    _species = (pet_profile.get("species") or "").lower() if pet_profile else ""
    _age_years = compute_age_years(pet_profile.get("birth_date") if pet_profile else None)

    # Universal Red Flag Detection
    red_flag = _detect_red_flags(message.message)

    # 3.55. Episode tracking
    try:
        _ep_valid = isinstance(structured_data, dict) and "error" not in structured_data
        _ep_symptom = structured_data.get("symptom") if _ep_valid else None
        _ep_medication = structured_data.get("medication") if _ep_valid else None
        episode_result = process_event(
            pet_id=message.pet_id,
            symptom=_ep_symptom,
            medication=_ep_medication,
            message_text=message.message,
        )
        if episode_result.get("episode_id") and _ep_valid:
            structured_data["episode_id"] = episode_result["episode_id"]
    except Exception as e:
        logger.error("[episode tracking] %s", e)
        episode_result = {"episode_id": None, "action": "standalone"}

    _t2_onboarding = time.perf_counter()

    # Variables formerly set by handle_onboarding — defaults for regular chat
    _onboarding_step = None
    _auto_follow = None
    _quick_replies = []
    _input_type = "text"
    _is_off_topic = False
    _onboarding_deterministic = False
    _ai_response_override = None
    _chat_history = []
    _onboarding_pet_id = None
    _onboarding_pet_name = None
    _onboarding_pet_card = None
    _onboarding_welcome_card = None
    _onboarding_preferred_reply = None
    _onboarding_user_flags = {}
    _onboarding_pending_q = None

    # Prefetch medical events — used by both clinical_decision and postprocess
    _all_medical_events = get_medical_events(pet_id=message.pet_id, limit=20) if not is_onboarding else []

    # 3.6. Clinical decision + safety layers (GDV, vital signs, absolute critical)
    if not is_onboarding:
        decision = build_full_clinical_decision(
            message_text=message.message,
            pet_id=message.pet_id,
            structured_data=structured_data,
            pet_profile=pet_profile,
            episode_result=episode_result,
            red_flag=red_flag,
            lethargy_level=_lethargy_level,
            temperature_value=_temperature_value,
            respiratory_rate=_respiratory_rate,
            seizure_duration=_seizure_duration,
            species=_species,
            age_years=_age_years,
            prev_events=_all_medical_events,
        )
    else:
        decision = None

    # Extract debug flags from clinical decision
    if decision is not None:
        _blood_type_adjusted = decision.get("blood_type_adjusted", False)
        _gdv_flag = decision.get("gdv_flag", False)
        _absolute_critical_flag = decision.get("absolute_critical_flag", False)
        _hyperthermia_critical = decision.get("hyperthermia_critical", False)
        _respiratory_adjusted = decision.get("respiratory_adjusted", False)
        _vital_override_triggered = decision.get("vital_override_triggered", False)
        _respiratory_recalibrated = decision.get("respiratory_recalibrated", False)
    else:
        _blood_type_adjusted = False
        _gdv_flag = False
        _absolute_critical_flag = False
        _hyperthermia_critical = False
        _respiratory_adjusted = False
        _vital_override_triggered = False

    # ── Systemic State — standalone decision creation ──
    _refusing_water = False
    if isinstance(structured_data, dict) and "error" not in structured_data:
        _refusing_water = bool(structured_data.get("refusing_water", False))

    # High temperature creates a standalone decision when none exists
    if isinstance(_temperature_value, float) and decision is None:
        if _temperature_value >= 39.5:
            decision = {
                "escalation": "LOW",
                "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
                "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
                "stop_questioning": True,
                "override_urgency": True,
            }

    # Refusing water + lethargy creates standalone decision when none exists (v4.3)
    if _refusing_water and _lethargy_level != "none" and decision is None:
        decision = {
            "escalation": "LOW",
            "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
            "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
            "stop_questioning": False,
            "override_urgency": False,
        }

    # Pre-fetch data needed by postprocess AND later stages
    recent_events = get_recent_events(pet_id=message.pet_id, limit=10) if not is_onboarding else []

    previous_assistant_text = None
    if not is_onboarding:
        try:
            _prev_ai = (
                supabase.table("chat")
                .select("message")
                .eq("pet_id", message.pet_id)
                .eq("role", "ai")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if _prev_ai.data:
                previous_assistant_text = _prev_ai.data[0]["message"]
        except Exception as _prev_err:
            logger.error("[prev_assistant] %s", _prev_err)

    _prev_summary = (previous_assistant_text or "")[:200] or None

    # ── Post-processing ──
    if decision and not is_onboarding:
        decision = postprocess_decision(
            decision=decision,
            structured_data=structured_data,
            message_text=message.message,
            pet_id=message.pet_id,
            pet_profile=pet_profile,
            episode_result=episode_result,
            prev_events=_all_medical_events,
            species=_species,
            age_years=_age_years,
            lethargy_level=_lethargy_level,
            refusing_water=_refusing_water,
            temperature_value=_temperature_value,
            previous_assistant_text=_prev_summary,
            recent_events=recent_events,
            supabase_client=supabase,
        )

    dialogue_mode = decision.get("dialogue_mode", "normal") if decision else "normal"

    # 4. Сохраняем medical_event ТОЛЬКО если есть symptom
    if (
        not is_onboarding
        and isinstance(structured_data, dict)
        and "error" not in structured_data
        and structured_data.get("symptom")
    ):
        save_medical_event(
            user_id=message.user_id,
            pet_id=message.pet_id,
            structured_data=structured_data,
            source_chat_id=chat_data_list[0]["id"] if chat_data_list else None,
            episode_id=episode_result.get("episode_id"),
            escalation_level=decision.get("escalation", "LOW") if decision else "LOW",
        )

    # 4.5. Memory context + temporal awareness + pending question from onboarding
    memory_context, temporal_flag = _build_memory_context(_all_medical_events)

    # Proactive pending_question on COMPLETE (from onboarding)
    if _onboarding_pending_q and _message_mode == "ONBOARDING_COMPLETE":
        memory_context = (memory_context or "") + (
            f"\n\nВо время онбординга пользователь спрашивал: \"{_onboarding_pending_q}\". "
            "После финального сообщения — ответь на этот вопрос кратко (2-3 предложения). "
            "Начни с: \"Кстати — вы спрашивали про...\""
        )

    if not is_onboarding:
        _uf = get_user_flags(message.user_id)
        _pending_q = _uf.get("pending_question")
        if _pending_q:
            memory_context = (memory_context or "") + (
                f"\n\nПользователь ранее спрашивал во время онбординга: \"{_pending_q}\". "
                "Ответь на этот вопрос первым делом, а потом продолжай."
            )
            _uf.pop("pending_question")
            update_user_flags(message.user_id, _uf)

    # 5. Urgency + escalation
    _urgency = _compute_urgency(structured_data, decision)
    urgency_score = _urgency["urgency_score"]
    risk_level = _urgency["risk_level"]
    sos = _urgency["sos"]
    needs_followup = _urgency["needs_followup"]
    escalation_message = _urgency["escalation_message"]
    followup_instructions = _urgency["followup_instructions"]

    # 8. AI ответ
    _prev_summary = (previous_assistant_text or "")[:200] or None

    _strict = (
        "NO QUESTIONS. STEP-BY-STEP INSTRUCTIONS. CALM BUT DIRECT. RUSSIAN."
        if decision and decision.get("response_type") == "ACTION"
        else None
    )

    # --- LLM CONTRACT BUILD ---
    raw_known_facts = {
        "symptom": structured_data.get("symptom"),
        "blood": structured_data.get("blood"),
        "lethargy_level": decision.get("lethargy_level") if decision else None,
        "refusing_water": decision.get("refusing_water") if decision else None,
        "temperature": decision.get("temperature_value") if decision else None,
        "food": structured_data.get("food") if isinstance(structured_data, dict) else None,
    }
    known_facts = {k: v for k, v in raw_known_facts.items() if v is not None}
    allowed_questions = build_missing_facts(structured_data)
    llm_contract = {
        "risk_level": decision.get("escalation") if decision else "LOW",
        "response_type": decision.get("response_type") if decision else "ASSESS",
        "episode_phase": decision.get("episode_phase") if decision else "initial",
        "known_facts": known_facts,
        "allowed_questions": allowed_questions,
        "max_questions": (
            2 if decision and decision.get("response_type") == "CLARIFY"
            else 1 if decision and decision.get("response_type") == "ASSESS"
            else 0
        ),
    }

    # ── Onboarding response ──
    if _onboarding_deterministic and _ai_response_override:
        ai_response = _ai_response_override
    else:
        _actual_message_mode = _message_mode
        _actual_chat_history = None
        _actual_strict = _next_question if _message_mode == "ONBOARDING" else _strict
        if _is_off_topic and _message_mode == "ONBOARDING" and _onboarding_step:
            _actual_message_mode = "ONBOARDING_OBSERVER"
            _actual_chat_history = _chat_history if _chat_history else None
            _actual_strict = _onboarding_step

        try:
            ai_response = generate_ai_response(AIResponseRequest(
                pet_profile=pet_profile,
                recent_events=recent_events,
                user_message=message.message,
                urgency_score=urgency_score,
                risk_level=risk_level,
                memory_context=memory_context,
                clinical_decision=decision,
                dialogue_mode=dialogue_mode,
                previous_assistant_text=_prev_summary,
                strict_override=_actual_strict,
                llm_contract=llm_contract,
                message_mode=_actual_message_mode,
                client_time=message.client_time,
                owner_name=_owner_name,
                chat_history=_actual_chat_history,
            ))
        except Exception as _ai_err:
            logger.error("[ai_response error] %s", _ai_err)
            ai_response = "Извини, произошла ошибка. Попробуй ещё раз через минуту."

    # Hard guard: ACTION / ACTION_HOME_PROTOCOL must not contain questions
    if (
        decision
        and decision.get("response_type") in ["ACTION", "ACTION_HOME_PROTOCOL"]
        and "?" in ai_response
    ):
        ai_response = generate_ai_response(AIResponseRequest(
            pet_profile=pet_profile,
            recent_events=recent_events,
            user_message=message.message,
            urgency_score=urgency_score,
            risk_level=risk_level,
            memory_context=memory_context,
            clinical_decision=decision,
            dialogue_mode=dialogue_mode,
            previous_assistant_text=_prev_summary,
            strict_override="NO QUESTIONS. STRICT ACTION STEPS ONLY. RUSSIAN LANGUAGE.",
            llm_contract=llm_contract,
            message_mode=_message_mode,
            client_time=message.client_time,
        ))

    # --- MAX QUESTIONS ENFORCEMENT GUARD (DAY 1.2) ---
    question_guard_triggered = False
    if llm_contract and not _onboarding_deterministic:
        max_q = llm_contract.get("max_questions", 0)
        if isinstance(max_q, int) and max_q >= 0:
            # максимум 2 попытки генерации
            for _ in range(2):
                actual_q = count_questions(ai_response)
                if actual_q <= max_q:
                    break
                question_guard_triggered = True
                ai_response = generate_ai_response(AIResponseRequest(
                    pet_profile=pet_profile,
                    recent_events=recent_events,
                    user_message=message.message,
                    urgency_score=urgency_score,
                    risk_level=risk_level,
                    memory_context=memory_context,
                    clinical_decision=decision,
                    dialogue_mode=dialogue_mode,
                    previous_assistant_text=_prev_summary,
                    strict_override=f"MAX {max_q} QUESTIONS. DO NOT EXCEED. RUSSIAN LANGUAGE.",
                    llm_contract=llm_contract,
                    message_mode=_message_mode,
                    client_time=message.client_time,
                ))
            # финальный аварийный fallback
            if count_questions(ai_response) > max_q:
                question_guard_triggered = True
                ai_response = ai_response.replace("?", ".")

    _t3_ai = time.perf_counter()

    # Persist AI response to chat table (linked to the user message)
    _user_chat_id = chat_data_list[0]["id"] if chat_data_list else None
    logger.debug("AI RESPONSE: %s", ai_response)
    logger.debug("LINKED ID: %s", _user_chat_id)
    try:
        supabase.table("chat").insert({
            "user_id": message.user_id,
            "pet_id": message.pet_id,
            "message": ai_response,
            "role": "ai",
            "linked_chat_id": _user_chat_id,
            "urgency_score": urgency_score,
            "risk_level": risk_level,
            "mode": _message_mode,
            "metadata": {
                "episode_id": episode_result.get("episode_id"),
                "dialogue_mode": dialogue_mode,
                "welcome_card": _onboarding_welcome_card,
            },
        }).execute()
        logger.debug("AI INSERT SUCCESS")
    except Exception as _ai_save_err:
        import traceback
        logger.error("[ai_persist ERROR]")
        traceback.print_exc()

    # Сохраняем auto_follow как отдельное сообщение в чат
    if isinstance(_auto_follow, dict):
        try:
            supabase.table("chat").insert({
                "user_id": message.user_id,
                "pet_id": message.pet_id,
                "message": _auto_follow["text"],
                "role": "ai",
                "mode": "auto_follow",
            }).execute()
        except Exception as _af_err:
            logger.error("[auto_follow persist] %s", _af_err)

    _linked_date = str(date.today()) if decision and structured_data.get("symptom") else None

    response_payload = {
        "chat_saved": chat_data_list,
        "pet_profile": pet_profile,
        "recent_events": recent_events,
        "structured_data": structured_data,
        "ai_response": ai_response,
        "urgency_score": urgency_score,
        "risk_level": risk_level,
        "sos": sos,
        "needs_followup": needs_followup,
        "escalation_message": escalation_message,
        "followup_instructions": followup_instructions,
        "linked_date": _linked_date,
        "response_type": _message_mode,
        "onboarding_phase": _onboarding_phase,
        "onboarding_field": _next_question,
        "owner_name": _owner_name,
        "quick_replies": _quick_replies,
        "input_type": _input_type,
        "auto_follow": _auto_follow,
        "pet_id": _onboarding_pet_id,
        "pet_name": _onboarding_pet_name,
        "pet_card": _onboarding_pet_card,
        "user_flags": _onboarding_user_flags,
        "welcome_card": _onboarding_welcome_card,
        "preferred_reply": _onboarding_preferred_reply,
    }

    # Persist final triage escalation to episode (monotonic invariant)
    if episode_result.get("episode_id") and decision:
        _ep_final_esc = decision.get("escalation")
        if _ep_final_esc:
            try:
                update_episode_escalation(episode_result["episode_id"], _ep_final_esc)
            except Exception as _ep_esc_err:
                logger.error("[episode escalation] %s", _ep_esc_err)

    if decision:
        response_payload["debug"] = {
            # Core
            "old_escalation": decision.get("escalation"),
            "calculated_escalation": decision.get("calculated_escalation"),
            "risk_score": decision.get("risk_score"),
            "dehydration_risk": decision.get("dehydration_risk"),
            "red_flag": decision.get("red_flag", False),
            "response_type": decision.get("response_type"),
            # Systemic state
            "lethargy_level": decision.get("lethargy_level"),
            "refusing_water": decision.get("refusing_water"),
            "temperature_value": decision.get("temperature_value"),
            "systemic_adjusted": decision.get("systemic_adjusted", False),
            "temp_lethargy_override": decision.get("temp_lethargy_override", False),
            # Species & age
            "species": _species or None,
            "age_years": round(_age_years, 2) if isinstance(_age_years, float) else None,
            "species_adjusted": decision.get("species_adjusted", False),
            "age_adjusted": decision.get("age_adjusted", False),
            "juvenile_adjusted": decision.get("juvenile_adjusted", False),
            # Episode clinical
            "episode_duration_hours": decision.get("episode_duration_hours"),
            "episode_phase": decision.get("episode_phase"),
            "recurrent_flag": decision.get("recurrent_flag", False),
            "recurrence_adjusted": decision.get("recurrence_adjusted", False),
            "episode_adjusted": decision.get("episode_adjusted", False),
            # Ingestion / cross-class
            "ingestion_adjusted": decision.get("ingestion_adjusted", False),
            "cross_class_override": decision.get("cross_class_override", False),
            "time_critical_window": decision.get("time_critical_window"),
            # v4.2 overrides
            "blood_type_adjusted": _blood_type_adjusted,
            "gdv_flag": _gdv_flag,
            "cat_anorexia_adjusted": decision.get("cat_anorexia_adjusted", False),
            "respiratory_recalibrated": _respiratory_recalibrated,
            # v4.3 vital signs
            "absolute_critical_flag": _absolute_critical_flag,
            "hyperthermia_critical": _hyperthermia_critical,
            "respiratory_rate": _respiratory_rate,
            "respiratory_adjusted": _respiratory_adjusted,
            "vital_override_triggered": _vital_override_triggered,
            # v4.4 new classes
            "seizure_duration": _seizure_duration,
            "urinary_straining": decision.get("urinary_straining", False),
            # LLM contract
            "llm_contract": llm_contract,
            "question_guard_triggered": question_guard_triggered,
            # v3.1 monotonic lock
            "monotonic_corrected": decision.get("monotonic_corrected", False),
            # Follow-up engine v1
            "follow_up_required": decision.get("follow_up_required", False),
            "follow_up_window_hours": decision.get("follow_up_window_hours"),
        }

    # Timeline recalculation
    if not is_onboarding:
        try:
            from routers.timeline import recalculate_day
            from datetime import date as _date_cls
            recalculate_day(pet_id=str(message.pet_id), date_str=str(_date_cls.today()))
        except Exception as _tl_err:
            logger.error("[timeline recalc] %s", _tl_err)

    _t4_end = time.perf_counter()
    logger.info(
        "[perf] extraction=%.2fs onboarding=%.2fs ai_response=%.2fs total=%.2fs",
        _t1_extraction - _t0,
        _t2_onboarding - _t1_extraction,
        _t3_ai - _t2_onboarding,
        _t4_end - _t0,
    )

    return response_payload
