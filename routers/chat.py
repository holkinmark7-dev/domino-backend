from fastapi import APIRouter
from schemas.chat import ChatMessage, MigrateUser
from fastapi.responses import JSONResponse
from routers.services.memory import (
    save_event,
    save_medical_event,
    get_recent_events,
    get_pet_profile,
    get_medical_events,
    update_pet_profile,
    get_onboarding_status,
    get_owner_name,
    save_owner_name,
    get_user_flags,
    update_user_flags,
)
from routers.services.ai import generate_ai_response, extract_event_data
from routers.services.symptom_registry import normalize_symptom
from routers.services.symptom_class_registry import get_symptom_class
from routers.services.clinical_engine import (
    get_symptom_stats,
    build_clinical_decision,
    apply_cross_symptom_override,
    check_clarification_needed,
)
from routers.services.risk_engine import calculate_risk_score, ESCALATION_ORDER
from routers.services.episode_manager import process_event, update_episode_escalation
from routers.services.recurrence import check_recurrence
from routers.services.episode_phase import compute_episode_phase
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
import json
import re
from datetime import datetime, timezone, timedelta, date

router = APIRouter()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def strip_markdown_json(raw: str) -> str:
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        return match.group(1).strip()
    return raw.strip()


def escalate_min(current: str, target: str) -> str:
    if ESCALATION_ORDER[current] < ESCALATION_ORDER[target]:
        return target
    return current


def compute_age_years(birth_date_str) -> float | None:
    if not birth_date_str:
        return None
    try:
        from datetime import date
        bd = date.fromisoformat(str(birth_date_str)[:10])
        return (date.today() - bd).days / 365.25
    except (ValueError, TypeError):
        return None


def count_questions(text: str) -> int:
    """
    Count logical questions, not raw '?' symbols.
    Rules:
    - Consecutive '?' count as ONE question.
    - Ignore '?' inside quotes.
    - Ignore markdown/code blocks.
    """
    if not isinstance(text, str):
        return 0

    # remove code blocks
    cleaned = re.sub(r"```[\s\S]*?```", "", text)

    # remove quoted text (supports multiple quote styles)
    quote_patterns = [
        r"\".*?\"",        # "..."
        r"\'.*?\'",        # '...'
        r"«.*?»",          # «...»
        r"\u201c.*?\u201d",  # "..."
        r"\u2018.*?\u2019",  # '...'
    ]
    for pattern in quote_patterns:
        cleaned = re.sub(pattern, "", cleaned)

    # collapse multiple ?
    cleaned = re.sub(r"\?+", "?", cleaned)

    return cleaned.count("?")


def build_missing_facts(structured_data: dict) -> list:
    missing = []

    if not isinstance(structured_data, dict):
        return missing

    symptom = structured_data.get("symptom")

    # blood unknown
    if "blood" not in structured_data:
        missing.append("blood")

    # drinking unknown
    if "refusing_water" not in structured_data:
        missing.append("drinking")

    # cross GI уточнения
    if symptom == "diarrhea":
        if structured_data.get("vomiting") is None:
            missing.append("vomiting")

    if symptom == "vomiting":
        if structured_data.get("diarrhea") is None:
            missing.append("diarrhea")

    return list(set(missing))


def apply_monotonic_lock(decision: dict, episode_id, previous_events: list) -> None:
    """
    Ensure escalation within an episode is monotonically non-decreasing.
    Mutates decision in place. Sets 'monotonic_corrected' debug flag.
    """
    previous_max = None
    for e in previous_events:
        content = e.get("content")
        if not isinstance(content, dict):
            continue
        if content.get("episode_id") == episode_id:
            prev_urgency = content.get("urgency_score")
            if isinstance(prev_urgency, int):
                if previous_max is None or prev_urgency > previous_max:
                    previous_max = prev_urgency

    if previous_max is not None:
        current_idx = ESCALATION_ORDER[decision["escalation"]]
        previous_idx = previous_max
        if current_idx < previous_idx:
            decision["escalation"] = list(ESCALATION_ORDER.keys())[previous_idx]
            decision["monotonic_corrected"] = True
        else:
            decision["monotonic_corrected"] = False
    else:
        decision["monotonic_corrected"] = False


def compute_episode_phase_v1(
    current_escalation: str,
    previous_max_urgency: int | None,
    monotonic_corrected: bool,
    systemic_adjusted: bool,
    cross_class_override: bool,
) -> str:
    """
    Classify the clinical trajectory of the current episode turn.

    Returns one of:
      "initial"    — no prior escalation data (first event in episode)
      "worsening"  — current escalation > previous
      "stable"     — current == previous, no new systemic / cross-class driver
      "progressing"— current == previous BUT driven by systemic_adjusted or cross_class
      "improving"  — monotonic lock held the level; raw would have been lower

    Never mutates inputs. Pure function.
    """
    if previous_max_urgency is None:
        return "initial"

    current_idx = ESCALATION_ORDER[current_escalation]

    # improving: lock corrected upward → the underlying trend is better
    if monotonic_corrected:
        return "improving"

    if current_idx > previous_max_urgency:
        return "worsening"

    if current_idx == previous_max_urgency:
        if systemic_adjusted or cross_class_override:
            return "progressing"
        return "stable"

    # current_idx < previous_max_urgency should be impossible post-lock
    return "stable"


def _classify_message_mode(structured_data: dict, message_text: str) -> str:
    """
    Classify the message into one of three routing modes:
      "CASUAL"   — no symptom, no lifestyle keyword (greeting, question about pet)
      "PROFILE"  — lifestyle / care / nutrition question
      "CLINICAL" — symptom detected
    """
    if not isinstance(structured_data, dict) or "error" in structured_data:
        return "CASUAL"

    # CLINICAL: symptom detected (highest priority)
    if structured_data.get("symptom"):
        return "CLINICAL"

    # PROFILE: lifestyle / care keywords
    _msg = message_text.lower()
    _profile_keywords = [
        "корм", "кормить", "питание", "еда", "вода", "поить",
        "прогулк", "гулять", "игр", "игруш",
        "уход", "мыть", "купать", "чесать", "стричь",
        "прививк", "вакцин", "паразит", "глист", "блох",
        "поведени", "характер", "порода", "возраст",
        "сколько", "как часто", "когда",
    ]
    if any(k in _msg for k in _profile_keywords):
        return "PROFILE"

    return "CASUAL"


@router.post("/chat")
def create_chat_message(message: ChatMessage):

    # 1. Сохраняем сообщение
    chat_data = supabase.table("chat").insert({
        "user_id": message.user_id,
        "pet_id": message.pet_id,
        "message": message.message,
        "role": "user",
    }).execute()
    print("USER INSERT DATA:", chat_data.data)

    # 2. Сохраняем chat_message
    save_event(
        user_id=message.user_id,
        pet_id=message.pet_id,
        event_type="chat_message",
        content=message.message
    )

    # 3. Extraction
    raw_structured = extract_event_data(message.message)
    cleaned = strip_markdown_json(raw_structured)

    try:
        structured_data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[extraction error] Failed to parse LLM response: {e}")
        structured_data = {"error": "invalid_json"}

    # 3.5. Symptom normalization
    if isinstance(structured_data, dict) and "error" not in structured_data:
        structured_data["symptom"] = normalize_symptom(structured_data.get("symptom"))
        structured_data["symptom_class"] = get_symptom_class(structured_data.get("symptom"))

    # Keyword override — deterministic safety net (priority: tox > blood type > anorexia)
    if isinstance(structured_data, dict) and "error" not in structured_data:
        _kw_msg = message.message.lower()
        _kw_override = None
        # Priority 1: Toxicology
        if "ксилит" in _kw_msg or "ксилитол" in _kw_msg:
            _kw_override = "xylitol_toxicity"
        elif "антифриз" in _kw_msg:
            _kw_override = "antifreeze"
        elif "крысиный яд" in _kw_msg or "отрава для крыс" in _kw_msg:
            _kw_override = "rodenticide"
        # Priority 2: Blood types
        elif any(k in _kw_msg for k in ["чёрный стул", "дёгтеобразный стул", "чёрный кал"]):
            _kw_override = "melena"
        elif any(k in _kw_msg for k in ["кофейная гуща", "кофейной гущей", "рвёт кофейной", "рвота кофейной"]):
            _kw_override = "coffee_ground_vomit"
        # Priority 3: Anorexia
        elif any(k in _kw_msg for k in ["не ест", "отказывается от еды", "не хочет есть"]):
            _kw_override = "anorexia"
        # Priority 4: Urinary obstruction
        elif any(k in _kw_msg for k in [
            "тужится", "не писает", "не может пописать", "не может помочиться",
            "мало мочи", "сидит в лотке", "часто ходит в лоток",
        ]):
            _kw_override = "urinary_obstruction"
        if _kw_override:
            structured_data["symptom"] = _kw_override
            structured_data["symptom_class"] = get_symptom_class(_kw_override)

    # Message mode classification — CASUAL / PROFILE / CLINICAL
    _message_mode = _classify_message_mode(structured_data, message.message)
    _next_question = None
    _owner_name = None
    _onboarding_phase = None

    # ── REGISTRATION PROMPT CHECK ─────────────────────────────────────
    _user_flags = get_user_flags(user_id=message.user_id)
    if _user_flags.get("show_registration_prompt") and _message_mode != "CLINICAL":
        _message_mode = "REGISTRATION_PROMPT"
        update_user_flags(user_id=message.user_id, flags={"show_registration_prompt": False})

    # ── OWNER NAME CHECK (ДО онбординга питомца) ─────────────────────
    if _message_mode != "REGISTRATION_PROMPT":
        _owner_name = get_owner_name(user_id=message.user_id)

        if not _owner_name and _message_mode != "CLINICAL":
            # Проверяем есть ли предыдущие AI-сообщения (уже спрашивали имя?)
            _prior_ai_check = supabase.table("chat").select("id").eq("user_id", message.user_id).eq("role", "ai").limit(1).execute()
            _already_asked = bool(_prior_ai_check.data)

            if _already_asked:
                # Пробуем распознать имя из текущего сообщения
                _raw = message.message.strip()
                if len(_raw) >= 2 and len(_raw) <= 40 and _raw.replace(" ", "").replace("-", "").isalpha():
                    save_owner_name(user_id=message.user_id, name=_raw.capitalize())
                    _owner_name = _raw.capitalize()

            if not _owner_name:
                # Имя ещё не получено — спрашиваем
                _message_mode = "ONBOARDING"
                _next_question = "owner_name"
                _onboarding_phase = "owner"

    # ── ONBOARDING override — только если нет симптома и профиль не заполнен
    if _next_question != "owner_name" and _message_mode != "REGISTRATION_PROMPT":
        _onboarding = get_onboarding_status(pet_id=message.pet_id)
        _onboarding_phase = _onboarding.get("phase")
        if not _onboarding["complete"] and _message_mode != "CLINICAL":
            _message_mode = "ONBOARDING"
            _next_question = _onboarding["next_question"]

    # ── CLARIFICATION CHECK ──────────────────────────────────────────
    # Проверяем нужен ли уточняющий вопрос перед генерацией ответа
    if _message_mode == "CLINICAL":
        _extracted_symptoms = []
        if isinstance(structured_data, dict) and "error" not in structured_data:
            _sym = structured_data.get("symptom")
            if _sym:
                _extracted_symptoms = [_sym]

        _clarif_pet = get_pet_profile(pet_id=message.pet_id) or {}
        _clarif_species = (_clarif_pet.get("species") or "dog").lower()

        clarification = check_clarification_needed(
            user_message=message.message,
            extracted_symptoms=_extracted_symptoms,
            species=_clarif_species
        )

        if clarification["needed"]:
            # Skip clarification if extraction already has rich detail
            _skip_clarification = False
            if isinstance(structured_data, dict):
                if isinstance(structured_data.get("urgency_score"), int) and structured_data["urgency_score"] >= 2:
                    _skip_clarification = True
                if structured_data.get("blood") is True:
                    _skip_clarification = True
                if structured_data.get("refusing_water") is True:
                    _skip_clarification = True
                if (structured_data.get("lethargy_level") or "none") != "none":
                    _skip_clarification = True
                if structured_data.get("temperature_value") is not None:
                    _skip_clarification = True
                if isinstance(structured_data.get("duration_hours"), (int, float)):
                    _skip_clarification = True
                if isinstance(structured_data.get("severity_hints"), list) and len(structured_data["severity_hints"]) > 0:
                    _skip_clarification = True

        if clarification["needed"] and not _skip_clarification:
            # Сохраняем уточняющий вопрос в чат
            _clarif_response = clarification["question"]
            supabase.table("chat").insert({
                "user_id": message.user_id,
                "pet_id": message.pet_id,
                "message": _clarif_response,
                "role": "ai",
            }).execute()

            return {
                "ai_response": _clarif_response,
                "structured_data": {
                    "escalation": "PENDING",
                    "symptom_key": clarification["symptom_key"],
                    "clarification": True
                },
                "risk_level": None,
                "chat_saved": [],
                "debug": {
                    "clarification_triggered": True,
                    "symptom_key": clarification["symptom_key"],
                    "all_symptoms": clarification["all_symptoms"],
                    "mode": "CLARIFICATION"
                }
            }
    # ── END CLARIFICATION CHECK ──────────────────────────────────────

    # Early lethargy extraction — used in clinical routing and systemic state layer
    _lethargy_level = "none"
    if isinstance(structured_data, dict) and "error" not in structured_data:
        _lethargy_level = structured_data.get("lethargy_level") or "none"
    _respiratory_recalibrated = False

    # Early vitals extraction — temperature and respiratory_rate for Absolute Critical block
    _temperature_value = None
    _respiratory_rate = None
    if isinstance(structured_data, dict) and "error" not in structured_data:
        _raw_temp = structured_data.get("temperature_value")
        if isinstance(_raw_temp, (int, float)):
            _temperature_value = float(_raw_temp)
        elif isinstance(_raw_temp, str):
            try:
                _temperature_value = float(_raw_temp)
            except (ValueError, TypeError):
                _temperature_value = None
        _rr_raw = structured_data.get("respiratory_rate")
        if isinstance(_rr_raw, (int, float)):
            _respiratory_rate = int(_rr_raw)

    _seizure_duration = None
    if isinstance(structured_data, dict) and "error" not in structured_data:
        _sd_raw = structured_data.get("seizure_duration")
        if isinstance(_sd_raw, (int, float)):
            _seizure_duration = float(_sd_raw)

    # Pet profile — early fetch for species/age and vital rules
    pet_profile = get_pet_profile(pet_id=message.pet_id)
    pet_profile = pet_profile or {}
    _species = (pet_profile.get("species") or "").lower() if pet_profile else ""
    _age_years = compute_age_years(pet_profile.get("birth_date") if pet_profile else None)

    # Universal Red Flag Detection
    red_flag = False
    _rf_text = message.message.lower()

    red_flag_keywords = [
        "судорог",
        "потерял сознание",
        "не дыш",
        "задыха",
        "кровотеч",
        "съел пакет",
        "проглотил",
        "инородн",
        "не вста",
        "паралич",
        "не моч",
        "лежит и не реаг",
        "не реаг",
    ]

    for keyword in red_flag_keywords:
        if keyword in _rf_text:
            red_flag = True
            break

    # 3.55. Episode tracking
    try:
        _ep_valid = isinstance(structured_data, dict) and "error" not in structured_data
        _ep_symptom = structured_data.get("symptom") if _ep_valid else None
        _ep_medication = structured_data.get("medication") if _ep_valid else None
        episode_result = process_event(
            pet_id=message.pet_id,
            symptom=_ep_symptom,
            medication=_ep_medication,
            message_text=message.message
        )
        if episode_result.get("episode_id") and _ep_valid:
            structured_data["episode_id"] = episode_result["episode_id"]
    except Exception as e:
        print(f"[episode tracking] {e}")
        episode_result = {"episode_id": None, "action": "standalone"}

    # 3.6. Clinical decision — только для CLINICAL режима
    if _message_mode == "CLINICAL":
        if structured_data.get("symptom_class") == "GI":
            stats = get_symptom_stats(
                pet_id=message.pet_id,
                symptom_key=structured_data.get("symptom")
            )

            # Explicit side-effect — current episode
            stats["today"] += 1
            stats["last_hour"] += 1
            stats["last_24h"] += 1

            decision = build_clinical_decision(structured_data.get("symptom"), stats)

            if decision and red_flag:
                decision["red_flag"] = True
                if decision["escalation"] in ["LOW", "MODERATE"]:
                    decision["escalation"] = "HIGH"

            # --- Escalation progression metrics ---
            previous_events = get_medical_events(pet_id=message.pet_id, limit=20)

            consecutive_escalations = 0
            consecutive_critical = 0

            for e in reversed(previous_events):
                content = e.get("content")
                if not isinstance(content, dict):
                    continue

                if content.get("episode_id") != structured_data.get("episode_id"):
                    break

                if content.get("symptom") != structured_data.get("symptom"):
                    break

                prev_urgency = content.get("urgency_score")

                if prev_urgency and prev_urgency >= 2:
                    consecutive_escalations += 1
                else:
                    break

                if prev_urgency and prev_urgency >= 3:
                    consecutive_critical += 1

            decision["consecutive_escalations"] = consecutive_escalations
            decision["consecutive_critical"] = consecutive_critical

            # Episode phase
            _ep_action = episode_result.get("action") if isinstance(episode_result, dict) else None
            if _ep_action == "resolved":
                episode_phase = "resolved"
            elif decision["stats"]["today"] <= 1:
                episode_phase = "initial"
            else:
                episode_phase = "progressing"

            decision["episode_phase"] = episode_phase

            # Hydration Risk Model v1 (GI Safety Layer)
            dehydration_risk = "NONE"

            if structured_data.get("symptom_class") == "GI":
                last_hour = decision["stats"].get("last_hour", 0)
                today = decision["stats"].get("today", 0)
                phase = decision.get("episode_phase")

                if last_hour >= 3 and phase == "progressing":
                    dehydration_risk = "HIGH"
                elif today >= 3:
                    dehydration_risk = "MODERATE"
                else:
                    dehydration_risk = "LOW"

            decision["dehydration_risk"] = dehydration_risk

            if isinstance(structured_data, dict) and structured_data.get("food"):
                decision["food"] = structured_data.get("food")

        elif structured_data.get("symptom_class") == "RESPIRATORY":
            stats = get_symptom_stats(
                pet_id=message.pet_id,
                symptom_key=structured_data.get("symptom")
            )

            # Explicit side-effect — current episode
            stats["today"] += 1
            stats["last_hour"] += 1
            stats["last_24h"] += 1

            symptom = structured_data.get("symptom")

            # difficulty_breathing + lethargy → CRITICAL
            if symptom == "difficulty_breathing" and _lethargy_level != "none":
                _esc = "CRITICAL"
                _respiratory_recalibrated = True
            # difficulty_breathing alone → HIGH
            elif symptom == "difficulty_breathing":
                _esc = "HIGH"
            # cough/sneezing + lethargy → MODERATE
            elif _lethargy_level != "none":
                _esc = "MODERATE"
                _respiratory_recalibrated = True
            # cough/sneezing repeated (today >= 2) → MODERATE (v4.4)
            elif stats["today"] >= 2:
                _esc = "MODERATE"
                _respiratory_recalibrated = True
            # cough/sneezing alone → LOW
            else:
                _esc = "LOW"

            decision = {
                "escalation": _esc,
                "stats": stats,
                "symptom": symptom,
                "stop_questioning": _esc in ["HIGH", "CRITICAL"],
                "override_urgency": _esc in ["HIGH", "CRITICAL"],
            }

            # Red flag priority: raise to HIGH if below
            if red_flag:
                decision["red_flag"] = True
                if decision["escalation"] in ["LOW", "MODERATE"]:
                    decision["escalation"] = "HIGH"

            if isinstance(structured_data, dict) and structured_data.get("food"):
                decision["food"] = structured_data.get("food")

        elif structured_data.get("symptom_class") == "INGESTION":
            symptom = structured_data.get("symptom")
            stats = get_symptom_stats(pet_id=message.pet_id, symptom_key=symptom)
            stats["today"] += 1
            stats["last_hour"] += 1
            stats["last_24h"] += 1

            if symptom in ["choking", "bone_stuck"]:
                _esc = "CRITICAL"
            else:
                _esc = "HIGH"  # foreign_body_ingestion and any unknown INGESTION

            decision = {
                "escalation": _esc,
                "stats": stats,
                "symptom": symptom,
                "stop_questioning": True,
                "override_urgency": True,
                "ingestion_adjusted": True,
            }

            if red_flag:
                decision["red_flag"] = True

            if isinstance(structured_data, dict) and structured_data.get("food"):
                decision["food"] = structured_data.get("food")

        elif structured_data.get("symptom_class") == "TOXIC":
            symptom = structured_data.get("symptom")
            stats = get_symptom_stats(pet_id=message.pet_id, symptom_key=symptom)
            stats["today"] += 1
            stats["last_hour"] += 1
            stats["last_24h"] += 1

            if symptom == "xylitol_toxicity":
                _esc = "CRITICAL"
                _tcw = "30min"
            elif symptom == "antifreeze":
                _esc = "CRITICAL"
                _tcw = "1h"
            elif symptom == "rodenticide":
                _esc = "HIGH"
                _tcw = "24h"
            else:
                _esc = "HIGH"
                _tcw = None

            decision = {
                "escalation": _esc,
                "stats": stats,
                "symptom": symptom,
                "stop_questioning": True,
                "override_urgency": True,
                "time_critical_window": _tcw,
            }

            if red_flag:
                decision["red_flag"] = True

            if isinstance(structured_data, dict) and structured_data.get("food"):
                decision["food"] = structured_data.get("food")

        elif structured_data.get("symptom_class") == "NEURO":
            symptom = structured_data.get("symptom")
            stats = get_symptom_stats(pet_id=message.pet_id, symptom_key=symptom)
            stats["today"] += 1
            stats["last_hour"] += 1
            stats["last_24h"] += 1

            # ≥2 seizures in 24h → CRITICAL
            if stats.get("last_24h", 0) >= 2:
                _esc = "CRITICAL"
            # seizure_duration ≥2 min → CRITICAL
            elif isinstance(_seizure_duration, float) and _seizure_duration >= 2.0:
                _esc = "CRITICAL"
            # single seizure <1 min → HIGH
            elif isinstance(_seizure_duration, float) and _seizure_duration < 1.0:
                _esc = "HIGH"
            # no duration info → HIGH (always at least HIGH)
            else:
                _esc = "HIGH"

            decision = {
                "escalation": _esc,
                "stats": stats,
                "symptom": symptom,
                "stop_questioning": True,
                "override_urgency": True,
            }

            if red_flag:
                decision["red_flag"] = True

            if isinstance(structured_data, dict) and structured_data.get("food"):
                decision["food"] = structured_data.get("food")

        elif structured_data.get("symptom_class") == "URINARY":
            symptom = structured_data.get("symptom")
            stats = get_symptom_stats(pet_id=message.pet_id, symptom_key=symptom)
            stats["today"] += 1
            stats["last_hour"] += 1
            stats["last_24h"] += 1

            _urinary_msg = message.message.lower()
            _urinary_straining = any(k in _urinary_msg for k in [
                "тужится", "не может пописать", "не может помочиться", "позывы без мочи",
            ])
            _urinary_pain = any(k in _urinary_msg for k in [
                "болит", "боль", "беспокойн", "кричит", "скулит",
            ])

            if _species == "cat":
                if _urinary_straining:
                    _esc = "CRITICAL"
                else:
                    _esc = "MODERATE"  # duration escalation handled in Episode Clinical Layer
            else:  # dog
                if _lethargy_level != "none" or _urinary_pain:
                    _esc = "HIGH"
                else:
                    _esc = "MODERATE"

            decision = {
                "escalation": _esc,
                "stats": stats,
                "symptom": symptom,
                "stop_questioning": _esc in ["HIGH", "CRITICAL"],
                "override_urgency": _esc in ["HIGH", "CRITICAL"],
                "urinary_straining": _urinary_straining,
            }

            if red_flag:
                decision["red_flag"] = True

            if isinstance(structured_data, dict) and structured_data.get("food"):
                decision["food"] = structured_data.get("food")

        elif structured_data.get("symptom_class") in ["GENERAL", "OCULAR", "SKIN", "MUSCULOSKELETAL"]:
            symptom = structured_data.get("symptom")
            stats = get_symptom_stats(pet_id=message.pet_id, symptom_key=symptom)
            stats["today"] += 1
            stats["last_hour"] += 1
            stats["last_24h"] += 1

            # Base escalation by symptom
            if symptom == "fever":
                _esc = "MODERATE"
            elif symptom in ["weakness", "lethargy"]:
                _esc = "LOW" if _lethargy_level == "mild" else "MODERATE"
            elif symptom == "anorexia":
                # anorexia + severe lethargy → HIGH
                if _lethargy_level == "severe":
                    _esc = "HIGH"
                # anorexia + refusing water → HIGH
                elif structured_data.get("refusing_water"):
                    _esc = "HIGH"
                # anorexia alone → MODERATE (отказ от еды всегда требует внимания)
                else:
                    _esc = "MODERATE"
            elif symptom == "eye_discharge":
                _esc = "LOW"
            else:
                _esc = "LOW"

            decision = {
                "escalation": _esc,
                "stats": stats,
                "symptom": symptom,
                "stop_questioning": False,
                "override_urgency": False,
            }

            if red_flag:
                decision["red_flag"] = True
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")

            if isinstance(structured_data, dict) and structured_data.get("food"):
                decision["food"] = structured_data.get("food")


        else:
            decision = None
    else:
        decision = None

    # Red Flag Fallback (when no decision exists)
    if red_flag and decision is None:
        decision = {
            "escalation": "HIGH",
            "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
            "red_flag": True,
            "symptom": None,
            "stop_questioning": True,
            "override_urgency": True,
        }

    # ── Blood Type Override Layer ─────────────────────────────────────────────
    _blood_type_adjusted = False
    if decision and isinstance(structured_data, dict):
        _bt_sym = structured_data.get("symptom")
        if _bt_sym in ["melena", "coffee_ground_vomit"]:
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            decision["stop_questioning"] = True
            decision["override_urgency"] = True
            _blood_type_adjusted = True
    # ─────────────────────────────────────────────────────────────────────────

    # ── GDV Override Layer ────────────────────────────────────────────────────
    _gdv_flag = False
    _gdv_msg = message.message.lower()
    _gdv_keywords = [
        "вздут", "раздуло живот", "живот раздуло",
        "пытается рвать но не может", "позывы без рвоты", "живот как барабан",
    ]
    if any(k in _gdv_msg for k in _gdv_keywords):
        _gdv_flag = True
        if decision is None:
            decision = {
                "escalation": "CRITICAL",
                "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
                "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
                "stop_questioning": True,
                "override_urgency": True,
            }
        else:
            decision["escalation"] = "CRITICAL"
            decision["stop_questioning"] = True
            decision["override_urgency"] = True
        decision["gdv_flag"] = True
    # ─────────────────────────────────────────────────────────────────────────

    # ── Absolute Critical & Vital Signs Layer (v4.3) ──────────────────────────
    _absolute_critical_flag = False
    _hyperthermia_critical = False
    _respiratory_adjusted = False
    _vital_override_triggered = False

    _ac_msg = message.message.lower()

    # Absolute critical keywords — unconditional CRITICAL
    _ac_keywords = [
        "не дышит", "агональное дыхание", "синие десны", "синюшные слизистые",
        "без сознания", "потерял сознание",
        "живот как барабан", "раздуло живот", "живот раздуло", "пытается рвать но не может",
        # Block F additions (v4.4)
        "внезапно ослеп", "ослепла", "ослеп", "резкая слепота",
        "кровотечение не останавл", "сильное кровотечение", "активное кровотечение",
        "серийные судороги", "судорожный статус", "статус эпилептикус",
    ]
    _has_open_mouth_cat = (
        ("открытая пасть" in _ac_msg or "дышит с открытым ртом" in _ac_msg or "рот открыт" in _ac_msg)
        and _species == "cat"
    )

    if any(k in _ac_msg for k in _ac_keywords) or _has_open_mouth_cat:
        _absolute_critical_flag = True
        _vital_override_triggered = True
        if decision is None:
            decision = {
                "escalation": "CRITICAL",
                "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
                "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
                "stop_questioning": True,
                "override_urgency": True,
            }
        else:
            decision["escalation"] = "CRITICAL"
            decision["stop_questioning"] = True
            decision["override_urgency"] = True
        decision["absolute_critical_flag"] = True

    # Temperature >= 41 → CRITICAL (hyperthermia)
    if isinstance(_temperature_value, float) and _temperature_value >= 41.0:
        _hyperthermia_critical = True
        _vital_override_triggered = True
        if decision is None:
            decision = {
                "escalation": "CRITICAL",
                "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
                "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
                "stop_questioning": True,
                "override_urgency": True,
            }
        else:
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            decision["stop_questioning"] = True
            decision["override_urgency"] = True
        decision["hyperthermia_critical"] = True

    # Temperature >= 40 + lethargy severe → CRITICAL
    if (
        isinstance(_temperature_value, float)
        and _temperature_value >= 40.0
        and _lethargy_level == "severe"
    ):
        _hyperthermia_critical = True
        _vital_override_triggered = True
        if decision is None:
            decision = {
                "escalation": "CRITICAL",
                "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
                "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
                "stop_questioning": True,
                "override_urgency": True,
            }
        else:
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            decision["stop_questioning"] = True
            decision["override_urgency"] = True
        decision["hyperthermia_critical"] = True

    # Respiratory rate rules
    if isinstance(_respiratory_rate, int):
        # Create standalone decision if needed
        if decision is None and _respiratory_rate >= 40:
            decision = {
                "escalation": "LOW",
                "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
                "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
                "stop_questioning": False,
                "override_urgency": False,
            }
        if decision:
            if _species == "cat":
                if _respiratory_rate >= 50:  # v4.4: lowered from >50 to >=50
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                        _vital_override_triggered = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
                elif _respiratory_rate >= 40:  # v4.4: lowered from >40 to >=40
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
            else:  # dog and other species
                if _respiratory_rate >= 50:  # v4.4: lowered from >50 to >=50
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                        _vital_override_triggered = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
                elif _respiratory_rate >= 40:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
    # ─────────────────────────────────────────────────────────────────────────

    # ── Systemic State Layer v1 ───────────────────────────────────────────────
    # _lethargy_level, _temperature_value already extracted before clinical routing
    _refusing_water = False
    _systemic_adjusted = False
    _temp_lethargy_override = False

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

    if decision:
        # Lethargy model — skipped for RESPIRATORY (lethargy already baked into clinical routing)
        _is_respiratory = isinstance(structured_data, dict) and structured_data.get("symptom_class") == "RESPIRATORY"
        if not _is_respiratory:
            if _lethargy_level == "mild":
                _cur = decision["escalation"]
                _idx = ESCALATION_ORDER[_cur]
                _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
                if _new != _cur:
                    decision["escalation"] = _new
                    _systemic_adjusted = True

            elif _lethargy_level == "severe":
                _before = decision["escalation"]
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                if decision["escalation"] != _before:
                    _systemic_adjusted = True

        # GI + refusing_water → CRITICAL (v4.4: raised from HIGH)
        if _refusing_water and isinstance(structured_data, dict) and structured_data.get("symptom_class") == "GI":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # GI + severe lethargy → CRITICAL (v4.4)
        if (
            _lethargy_level == "severe"
            and isinstance(structured_data, dict)
            and structured_data.get("symptom_class") == "GI"
        ):
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # Refusing water + lethargy → min HIGH (v4.3 tightening)
        if _refusing_water and _lethargy_level != "none":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # Refusing water + lethargy + GI → CRITICAL (v4.3 tightening)
        if (
            _refusing_water
            and _lethargy_level != "none"
            and isinstance(structured_data, dict)
            and structured_data.get("symptom_class") == "GI"
        ):
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

        # Temperature escalation (v4.4 recalibrated)
        if isinstance(_temperature_value, float):
            _before = decision["escalation"]
            if _temperature_value >= 40.0:
                # ≥40 → HIGH; ≥41 already locked CRITICAL by Absolute Critical Layer
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                _systemic_adjusted = True
            elif _temperature_value >= 39.7:
                # 39.7–39.9 → MODERATE (v4.4: new threshold)
                decision["escalation"] = escalate_min(decision["escalation"], "MODERATE")
                if decision["escalation"] != _before:
                    _systemic_adjusted = True
            elif _temperature_value < 37.5:
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                if decision["escalation"] != _before:
                    _systemic_adjusted = True

        # Temp + lethargy combined (v4.4: any lethargy + ≥40 → CRITICAL)
        if isinstance(_temperature_value, float) and _lethargy_level != "none":
            if _temperature_value >= 40.0:
                decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                _systemic_adjusted = True
                _temp_lethargy_override = True
            elif _temperature_value >= 39.7:
                _before = decision["escalation"]
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                if decision["escalation"] != _before:
                    _systemic_adjusted = True
                _temp_lethargy_override = True

        decision["lethargy_level"] = _lethargy_level
        decision["refusing_water"] = _refusing_water
        decision["temperature_value"] = _temperature_value
        decision["systemic_adjusted"] = _systemic_adjusted
        decision["temp_lethargy_override"] = _temp_lethargy_override
    # ─────────────────────────────────────────────────────────────────────────

    # ── Species & Age Multipliers ─────────────────────────────────────────────
    # _species, _age_years already extracted before clinical routing
    _species_adjusted = False
    _age_adjusted = False
    _juvenile_adjusted = False

    if decision:
        # Cat + RESPIRATORY → escalation min HIGH
        if _species == "cat" and isinstance(structured_data, dict) and structured_data.get("symptom_class") == "RESPIRATORY":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            if decision["escalation"] != _before:
                _species_adjusted = True

        # Cat + difficulty_breathing + lethargy → CRITICAL (v4.2)
        if (
            _species == "cat"
            and isinstance(structured_data, dict)
            and structured_data.get("symptom") == "difficulty_breathing"
            and _lethargy_level != "none"
        ):
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _species_adjusted = True

        # Puppy / kitten (age < 1 year) + GI → escalation +1
        if (
            isinstance(_age_years, float)
            and _age_years < 1
            and isinstance(structured_data, dict)
            and structured_data.get("symptom_class") == "GI"
        ):
            _cur = decision["escalation"]
            _idx = ESCALATION_ORDER[_cur]
            _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
            if _new != _cur:
                decision["escalation"] = _new
                _age_adjusted = True

        # Juvenile (age < 0.5 year) + GI + lethargy or refusing_water → CRITICAL (v4.3)
        if (
            isinstance(_age_years, float)
            and _age_years < 0.5
            and isinstance(structured_data, dict)
            and structured_data.get("symptom_class") == "GI"
            and (_lethargy_level != "none" or _refusing_water)
        ):
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            if decision["escalation"] != _before:
                _juvenile_adjusted = True

        # Senior (age >= 10) + systemic_adjusted → escalation +1
        if (
            isinstance(_age_years, float)
            and _age_years >= 10
            and decision.get("systemic_adjusted")
        ):
            _cur = decision["escalation"]
            _idx = ESCALATION_ORDER[_cur]
            _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
            if _new != _cur:
                decision["escalation"] = _new
                _age_adjusted = True

        decision["species_adjusted"] = _species_adjusted
        decision["age_adjusted"] = _age_adjusted
        decision["juvenile_adjusted"] = _juvenile_adjusted
    # ─────────────────────────────────────────────────────────────────────────

    # ── Episode Clinical Layer v1 ─────────────────────────────────────────────
    _episode_duration_hours = None
    _episode_phase = None
    _episode_adjusted = False
    _recurrent_flag = False
    _recurrence_adjusted = False

    _ep_id = episode_result.get("episode_id") if isinstance(episode_result, dict) else None
    _ep_symptom = structured_data.get("symptom") if isinstance(structured_data, dict) else None
    _ep_class = structured_data.get("symptom_class") if isinstance(structured_data, dict) else None

    if _ep_id and _ep_symptom and decision:
        # Duration logic
        try:
            _ep_row = (
                supabase.table("episodes")
                .select("started_at, status")
                .eq("id", _ep_id)
                .single()
                .execute()
            )
            if _ep_row.data:
                _started_at_str = _ep_row.data.get("started_at")
                if _started_at_str:
                    _started_at = datetime.fromisoformat(_started_at_str)
                    if _started_at.tzinfo is None:
                        _started_at = _started_at.replace(tzinfo=timezone.utc)
                    _now = datetime.now(timezone.utc)
                    _episode_duration_hours = (_now - _started_at).total_seconds() / 3600

                    # Episode phase
                    if _episode_duration_hours < 12:
                        _episode_phase = "initial"
                    elif _episode_duration_hours < 48:
                        _episode_phase = "ongoing"
                    else:
                        _episode_phase = "prolonged"

                    # Duration escalation — GI (v4.4: species-aware thresholds)
                    if _ep_class == "GI":
                        if isinstance(_age_years, float) and _age_years < 0.5:
                            # Puppy <6m: ≥6h → HIGH
                            if _episode_duration_hours >= 6:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True
                        elif _species == "cat":
                            # Cat: ≥12h → HIGH
                            if _episode_duration_hours >= 12:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True
                        else:
                            # Adult dog: ≥12h → MODERATE, ≥24h → HIGH
                            if _episode_duration_hours >= 24:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True
                            elif _episode_duration_hours >= 12:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "MODERATE")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True

                    # Duration escalation — RESPIRATORY
                    elif _ep_class == "RESPIRATORY":
                        if _episode_duration_hours >= 48:
                            _cur = decision["escalation"]
                            _idx = ESCALATION_ORDER[_cur]
                            _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
                            if _new != _cur:
                                decision["escalation"] = _new
                                _episode_adjusted = True

                    # Duration escalation — URINARY (v4.4)
                    elif _ep_class == "URINARY":
                        if _species == "cat":
                            if _episode_duration_hours >= 24:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True
                            elif _episode_duration_hours >= 12:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True
                        else:  # dog
                            if _episode_duration_hours >= 24:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True

        except Exception as e:
            print(f"[episode_clinical] duration fetch failed: {e}")

        # Episode Phase Display Layer — display-only, no escalation effect
        # See routers/services/episode_phase.py; None duration → "initial"
        _episode_phase = compute_episode_phase(_episode_duration_hours)

        # Recurrence Layer — see routers/services/recurrence.py
        _recurrence_adjusted = False
        try:
            _recurrent_flag = check_recurrence(str(message.pet_id), _ep_symptom)
            if _recurrent_flag and decision["escalation"] != "CRITICAL":
                _cur = decision["escalation"]
                _idx = ESCALATION_ORDER[_cur]
                _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
                if _new != _cur:
                    decision["escalation"] = _new
                    _recurrence_adjusted = True
                    _episode_adjusted = True
        except Exception as e:
            print(f"[episode_clinical] recurrence fetch failed: {e}")

    if decision:
        decision["episode_duration_hours"] = (
            round(_episode_duration_hours, 1) if isinstance(_episode_duration_hours, float) else None
        )
        decision["episode_phase"] = compute_episode_phase(_episode_duration_hours)
        decision["recurrent_flag"] = _recurrent_flag
        decision["episode_adjusted"] = _episode_adjusted
        decision["recurrence_adjusted"] = _recurrence_adjusted
    # ─────────────────────────────────────────────────────────────────────────

    # ── Cat Anorexia Override (v4.2) ──────────────────────────────────────────
    _cat_anorexia_adjusted = False
    if (
        decision
        and _species == "cat"
        and isinstance(structured_data, dict)
        and structured_data.get("symptom") == "anorexia"
    ):
        _anorexia_duration = decision.get("episode_duration_hours")
        if isinstance(_anorexia_duration, float) and _anorexia_duration >= 24:
            if _lethargy_level != "none":
                _before = decision["escalation"]
                decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                if decision["escalation"] != _before:
                    _cat_anorexia_adjusted = True
            else:
                _before = decision["escalation"]
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                if decision["escalation"] != _before:
                    _cat_anorexia_adjusted = True
            if _cat_anorexia_adjusted:
                decision["stop_questioning"] = True
                decision["override_urgency"] = True
    # ─────────────────────────────────────────────────────────────────────────

    # ── Cross-Class Override Layer ────────────────────────────────────────────
    _cross_class_override = False

    if decision:
        _msg_lower = message.message.lower()
        _sym = structured_data.get("symptom") if isinstance(structured_data, dict) else None
        _cls = structured_data.get("symptom_class") if isinstance(structured_data, dict) else None

        _toxic_mention = any(k in _msg_lower for k in [
            "яд", "токсин", "отравил", "антифриз", "ксилит", "крысиный яд",
        ])
        _has_seizure = (
            _sym == "seizure"
            or any(k in _msg_lower for k in ["судорог", "припадок", "эпилепс", "судорожит"])
        )
        _has_vomiting = (
            _sym == "vomiting"
            or any(k in _msg_lower for k in ["рвёт", "рвота", "вырвал", "вырвало", "рвать"])
        )
        _has_collapse = any(k in _msg_lower for k in [
            "коллапс", "потерял сознание", "упал и не встаёт",
        ])

        # NEURO + toxic context → CRITICAL
        if _cls == "NEURO" and _toxic_mention:
            decision["escalation"] = "CRITICAL"
            _cross_class_override = True

        # Seizure + vomiting → CRITICAL
        if _has_seizure and _has_vomiting:
            decision["escalation"] = "CRITICAL"
            _cross_class_override = True

        # Foreign body + vomiting → CRITICAL
        _has_foreign_body = (
            _sym == "foreign_body_ingestion"
            or any(k in _msg_lower for k in [
                "проглотил пакет", "проглотил игрушку", "съел носок", "инородн",
            ])
        )
        if _has_foreign_body and _has_vomiting:
            decision["escalation"] = "CRITICAL"
            _cross_class_override = True

        # Collapse → CRITICAL
        if _has_collapse:
            decision["escalation"] = "CRITICAL"
            _cross_class_override = True

        decision["cross_class_override"] = _cross_class_override
    # ─────────────────────────────────────────────────────────────────────────

    # Reaction classification
    reaction_type = "normal_progress"

    recent_events = get_recent_events(pet_id=message.pet_id, limit=10)

    previous_assistant_text = None
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
        print(f"[prev_assistant] {_prev_err}")

    user_text = message.message.lower()

    # 1. Repeated symptom detection
    if structured_data.get("symptom") and len(user_text.strip()) < 20:
        # Only mark as repeated if there's actual prior history of this symptom
        _prior_same = any(
            e.get("content", {}).get("symptom") == structured_data.get("symptom")
            for e in recent_events
            if isinstance(e.get("content"), dict)
        )
        if _prior_same:
            reaction_type = "repeated_symptom"

    # 2. Ignored urgent advice
    if decision and decision["escalation"] in ["HIGH", "CRITICAL"]:
        if previous_assistant_text and "ветеринар" in previous_assistant_text.lower():
            if structured_data.get("symptom"):
                reaction_type = "ignored_urgent_advice"

    # 3. Topic shift
    if structured_data.get("symptom") is None and decision and decision["escalation"] in ["HIGH", "CRITICAL"]:
        reaction_type = "topic_shift"

    # 4. Panic detection
    if "!!!" in user_text or "помог" in user_text:
        reaction_type = "panic"

    if decision:
        decision["reaction_type"] = reaction_type

    # Intent classification
    message_text = message.message.lower()

    if any(x in message_text for x in [
        "что делать",
        "что мне делать",
        "как быть",
        "помоги",
        "что теперь",
    ]):
        user_intent = "SEEKING_ACTION"

    elif any(x in message_text for x in [
        "не могу",
        "нет возможности",
        "не получится",
        "далеко",
    ]):
        user_intent = "EXPRESSING_LIMITATION"

    elif any(x in message_text for x in [
        "снова",
        "ещё",
        "опять",
    ]):
        user_intent = "PROVIDING_INFO"

    else:
        user_intent = "NEUTRAL"

    # Constraint detection
    if any(x in message_text for x in [
        "не могу идти",
        "не могу поехать",
        "нет клиники",
        "далеко до ветеринара",
    ]):
        constraint = "no_vet_access"
    else:
        constraint = "none"

    if decision:
        decision["user_intent"] = user_intent
        decision["constraint"] = constraint

    # Cross-symptom risk override
    if decision:
        decision = apply_cross_symptom_override(
            pet_id=message.pet_id,
            symptom_key=structured_data.get("symptom"),
            decision=decision
        )

    # Risk Engine v1 — parallel scoring, logging only, does NOT affect escalation
    if decision:
        risk_result = calculate_risk_score(
            symptom_key=structured_data.get("symptom"),
            stats=decision.get("stats", {}),
            blood=structured_data.get("blood", False),
            episode_phase=decision.get("episode_phase"),
            has_combo=decision.get("has_combo", False)
        )
        old_escalation = decision.get("escalation")
        new_escalation = risk_result["calculated_escalation"]

        if ESCALATION_ORDER[new_escalation] < ESCALATION_ORDER[old_escalation]:
            guarded_escalation = old_escalation
        else:
            guarded_escalation = new_escalation

        decision["risk_score"] = risk_result["risk_score"]
        decision["calculated_escalation"] = guarded_escalation
        print("[risk_engine]",
              "old:", old_escalation,
              "guarded:", guarded_escalation,
              "score:", risk_result["risk_score"])

    # Response type
    if decision:
        _escalation = decision["escalation"]

        # Escalation Behavior Lock
        if decision.get("red_flag") or _escalation in ["HIGH", "CRITICAL"]:
            response_type = "ACTION"
        elif _escalation == "MODERATE":
            response_type = "CLARIFY"
        else:
            response_type = "ASSESS"

        decision["response_type"] = response_type

    # dialogue_mode — вычисляется ПОСЛЕ всех override слоёв
    dialogue_mode = (
        "clinical_escalation"
        if decision and decision["escalation"] in ["MODERATE", "HIGH", "CRITICAL"]
        else "normal"
    )

    # 4. Сохраняем medical_event ТОЛЬКО если есть symptom
    if (
        isinstance(structured_data, dict)
        and "error" not in structured_data
        and structured_data.get("symptom")
    ):
        save_medical_event(
            user_id=message.user_id,
            pet_id=message.pet_id,
            structured_data=structured_data,
            source_chat_id=chat_data.data[0]["id"] if chat_data.data else None
        )

    # 4.5. Memory context + temporal awareness
    _mem_risk_map = {0: "normal", 1: "low", 2: "moderate", 3: "high"}
    _all_medical_events = get_medical_events(pet_id=message.pet_id, limit=20)
    if _all_medical_events:
        _lines = []
        _last_valid_ts = None
        for _e in _all_medical_events:
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
    else:
        memory_context = "No prior medical history."
        temporal_flag = "no_history"

    # 5. urgency + escalation
    if "error" in structured_data:
        urgency_score = None
    else:
        raw_urgency = structured_data.get("urgency_score", 0)
        if isinstance(raw_urgency, int) and 0 <= raw_urgency <= 3:
            urgency_score = raw_urgency
        else:
            urgency_score = None

    # Apply clinical override: override_urgency forces urgency_score to max
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

    if isinstance(urgency_score, int) and urgency_score >= 2:
        followup_instructions = "Следите за дыханием, аппетитом и активностью в течение следующих 24 часов."
    else:
        followup_instructions = None

    # 8. AI ответ
    _prev_summary = (previous_assistant_text or "")[:200] or None

    _strict = (
        "NO QUESTIONS. STEP-BY-STEP INSTRUCTIONS. CALM BUT DIRECT. RUSSIAN."
        if decision and decision.get("response_type") == "ACTION"
        else None
    )

    # Prefetch _prev_events for episode phase computation (reused by monotonic lock below)
    _prev_events = []
    if episode_result.get("episode_id") and decision:
        try:
            _prev_events = _all_medical_events
        except Exception as _pe_err:
            print(f"[episode_phase_prefetch] {_pe_err}")

    # --- EPISODE PHASE ENGINE v1 ---
    if decision:
        _ep_id_for_phase = episode_result.get("episode_id") if isinstance(episode_result, dict) else None
        _phase_prev_max: int | None = None
        if _prev_events and _ep_id_for_phase:
            for _pe in _prev_events:
                _pc = _pe.get("content")
                if not isinstance(_pc, dict):
                    continue
                if _pc.get("episode_id") == _ep_id_for_phase:
                    _pu = _pc.get("urgency_score")
                    if isinstance(_pu, int):
                        if _phase_prev_max is None or _pu > _phase_prev_max:
                            _phase_prev_max = _pu

        decision["episode_phase"] = compute_episode_phase_v1(
            current_escalation=decision["escalation"],
            previous_max_urgency=_phase_prev_max,
            monotonic_corrected=decision.get("monotonic_corrected", False),
            systemic_adjusted=decision.get("systemic_adjusted", False),
            cross_class_override=decision.get("cross_class_override", False),
        )
    # ─────────────────────────────────────────────────────────────────────────

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

    # Извлекаем ответ пользователя для онбординга
    if _message_mode == "ONBOARDING" and _next_question and _next_question != "owner_name":
        _msg_lower = message.message.lower().strip()
        _profile_update = {}

        # Детектор "не знаю" / пропуска — пропускаем поле
        _skip_keywords = [
            "не знаю", "незнаю", "не помню", "пропустить", "пропусти",
            "потом", "позже", "не уверен", "не уверена", "пропуск", "skip",
            "не хочу", "нет",
        ]
        _user_wants_skip = any(kw in _msg_lower for kw in _skip_keywords)

        # Полный порядок полей для fallback навигации
        _full_field_order = [
            "species", "name", "gender", "neutered", "age",
            "photo", "breed", "color", "features", "chip_id", "stamp_id",
        ]

        if _user_wants_skip:
            _skip_marker = {f"{_next_question}_skipped": True}
            update_pet_profile(pet_id=message.pet_id, fields=_skip_marker)
            _onboarding_recheck = get_onboarding_status(pet_id=message.pet_id)
            if _onboarding_recheck.get("next_question") == _next_question:
                # Последний resort: двигаемся по порядку
                _current_idx = _full_field_order.index(_next_question) if _next_question in _full_field_order else -1
                if _current_idx >= 0 and _current_idx < len(_full_field_order) - 1:
                    _next_question = _full_field_order[_current_idx + 1]
                else:
                    _next_question = None
            else:
                _next_question = _onboarding_recheck.get("next_question")
                _onboarding_phase = _onboarding_recheck.get("phase")
        else:
            # ── Парсинг текущего вопроса ──
            if _next_question == "name":
                import re as _re
                _raw_name = message.message.strip()

                _stop_words = [
                    "его зовут", "её зовут", "кличка", "имя", "зовут",
                    "мой", "моя", "наш", "наша", "питомец", "кот", "кошка",
                    "собака", "пёс", "пес", "щенок",
                ]
                _cleaned_name = _raw_name.lower()
                for sw in _stop_words:
                    _cleaned_name = _cleaned_name.replace(sw, "").strip()

                _name_match = _re.search(r"([А-ЯЁA-Z][а-яёa-z]{1,20})", _raw_name)
                if _name_match:
                    _candidate = _name_match.group(1)
                    _bad_starts = ["Мой", "Моя", "Наш", "Наша", "Его", "Её", "Это"]
                    if _candidate not in _bad_starts:
                        _profile_update["name"] = _candidate
                    else:
                        _all_caps = _re.findall(r"([А-ЯЁA-Z][а-яёa-z]{1,20})", _raw_name)
                        _filtered = [w for w in _all_caps if w not in _bad_starts]
                        if _filtered:
                            _profile_update["name"] = _filtered[0]

                if not _profile_update.get("name") and _cleaned_name:
                    _first_word = _cleaned_name.split()[0] if _cleaned_name.split() else ""
                    if 2 <= len(_first_word) <= 20 and _first_word.isalpha():
                        _profile_update["name"] = _first_word.capitalize()

                if not _profile_update.get("name"):
                    _words = _raw_name.strip().split()
                    if len(_words) == 1 and 2 <= len(_words[0]) <= 20:
                        _profile_update["name"] = _words[0].capitalize()

            elif _next_question == "species":
                if any(w in _msg_lower for w in ["кошк", "кот", "кис", "кошеч"]):
                    _profile_update["species"] = "cat"
                elif any(w in _msg_lower for w in ["собак", "пёс", "пес", "щенок", "щен"]):
                    _profile_update["species"] = "dog"

            elif _next_question == "gender":
                if any(w in _msg_lower for w in ["мальчик", "самец", "кот ", "пёс ", "он ", "м"]):
                    _profile_update["gender"] = "male"
                elif any(w in _msg_lower for w in ["девочк", "самка", "кошка ", "она ", "ж"]):
                    _profile_update["gender"] = "female"

            elif _next_question == "neutered":
                if any(w in _msg_lower for w in ["да", "кастрир", "стерил"]):
                    _profile_update["neutered"] = True
                elif any(w in _msg_lower for w in ["нет", "не кастр", "не стерил", "не "]):
                    _profile_update["neutered"] = False

            elif _next_question == "age":
                import re as _re
                _year_match = _re.search(r"(\d{4})", _msg_lower)
                _age_match = _re.search(r"(\d+)\s*(лет|год|года|мес)", _msg_lower)
                _num_only = _re.search(r"^(\d+)$", _msg_lower)
                if _year_match:
                    _profile_update["birth_date"] = f"{_year_match.group(1)}-01-01"
                elif _age_match:
                    _profile_update["age_years"] = int(_age_match.group(1))
                elif _num_only:
                    _profile_update["age_years"] = int(_num_only.group(1))

            elif _next_question == "photo":
                if hasattr(message, 'image_url') and message.image_url:
                    _profile_update["photo_url"] = message.image_url
                else:
                    _skip_words_photo = ["пропустить", "пропусти", "потом", "позже", "нет", "skip", "не хочу"]
                    if any(w in _msg_lower for w in _skip_words_photo):
                        update_pet_profile(pet_id=message.pet_id, fields={"photo_skipped": True})

            elif _next_question == "breed":
                _raw_breed = message.message.strip()
                _unknown_breed = ["не знаю", "незнаю", "не уверен", "смешанная", "дворняга",
                                  "дворняжка", "беспородный", "беспородная", "метис"]
                if any(w in _msg_lower for w in _unknown_breed):
                    _profile_update["breed"] = "unknown"
                elif len(_raw_breed) >= 2:
                    _profile_update["breed"] = _raw_breed.capitalize()

            elif _next_question == "color":
                _raw_color = message.message.strip()
                if len(_raw_color) >= 2:
                    _profile_update["color"] = _raw_color.lower()

            elif _next_question == "features":
                _raw_features = message.message.strip()
                _no_features = ["нет", "нету", "никаких", "обычный", "обычная", "не знаю"]
                if any(w in _msg_lower for w in _no_features):
                    _profile_update["features"] = "none"
                elif len(_raw_features) >= 2:
                    _profile_update["features"] = _raw_features

            elif _next_question == "chip_id":
                import re as _re
                _chip_match = _re.search(r'\b(\d{9,15})\b', message.message)
                _no_chip = ["нет", "нету", "не чипирован", "без чипа", "не знаю"]
                if _chip_match:
                    _profile_update["chip_id"] = _chip_match.group(1)
                elif any(w in _msg_lower for w in _no_chip):
                    _profile_update["chip_id"] = "none"

            elif _next_question == "stamp_id":
                import re as _re
                _stamp_match = _re.search(r'\b([A-Za-z\u0410-\u042F\u0401\u0430-\u044F\u0451]{0,3}\d{3,8})\b', message.message)
                _no_stamp = ["нет", "нету", "без клейма", "не знаю"]
                if _stamp_match:
                    _profile_update["stamp_id"] = _stamp_match.group(1).upper()
                elif any(w in _msg_lower for w in _no_stamp):
                    _profile_update["stamp_id"] = "none"

            # ── Бонус: извлечь доп. поля из того же сообщения при вводе имени ──
            if _next_question == "name" and _profile_update.get("name"):
                if any(w in _msg_lower for w in ["кошк", "кот", "кис"]):
                    _profile_update["species"] = "cat"
                elif any(w in _msg_lower for w in ["собак", "пёс", "пес", "щенок"]):
                    _profile_update["species"] = "dog"
                import re as _re
                _age_bonus = _re.search(r"(\d+)\s*(лет|год|года)", _msg_lower)
                if _age_bonus:
                    _profile_update["age_years"] = int(_age_bonus.group(1))
                if any(w in _msg_lower for w in ["мальчик", "самец", "кастрир"]):
                    _profile_update["gender"] = "male"
                elif any(w in _msg_lower for w in ["девочк", "самка", "стерил"]):
                    _profile_update["gender"] = "female"
                if "кастрир" in _msg_lower:
                    _profile_update["neutered"] = True
                    _profile_update["gender"] = "male"
                elif "стерил" in _msg_lower:
                    _profile_update["neutered"] = True
                    _profile_update["gender"] = "female"

            # ── Сохранение ──
            if _profile_update:
                update_pet_profile(pet_id=message.pet_id, fields=_profile_update)

            # ── AI-реакция на имя (микро-шаг) ──
            if _next_question == "name" and _profile_update.get("name"):
                _next_question = "name_reaction"
            else:
                # Перепроверяем статус после сохранения
                _onboarding_recheck = get_onboarding_status(pet_id=message.pet_id)
                _onboarding_phase = _onboarding_recheck.get("phase")
                if not _onboarding_recheck["complete"]:
                    _next_question = _onboarding_recheck["next_question"]
                else:
                    _next_question = None
                    _message_mode = "ONBOARDING_COMPLETE"
                    # Запланировать предложение регистрации на следующее сообщение
                    update_user_flags(user_id=message.user_id, flags={"show_registration_prompt": True})

    ai_response = generate_ai_response(
        pet_profile=pet_profile,
        recent_events=recent_events,
        user_message=message.message,
        urgency_score=urgency_score,
        risk_level=risk_level,
        memory_context=memory_context,
        clinical_decision=decision,
        dialogue_mode=dialogue_mode,
        previous_assistant_text=_prev_summary,
        strict_override=_next_question if _message_mode == "ONBOARDING" else _strict,
        llm_contract=llm_contract,
        message_mode=_message_mode,
        client_time=message.client_time,
        owner_name=_owner_name,
    )

    # Hard guard: ACTION / ACTION_HOME_PROTOCOL must not contain questions
    if (
        decision
        and decision.get("response_type") in ["ACTION", "ACTION_HOME_PROTOCOL"]
        and "?" in ai_response
    ):
        ai_response = generate_ai_response(
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
        )

    # --- MAX QUESTIONS ENFORCEMENT GUARD (DAY 1.2) ---
    question_guard_triggered = False
    if llm_contract:
        max_q = llm_contract.get("max_questions", 0)
        if isinstance(max_q, int) and max_q >= 0:
            # максимум 2 попытки генерации
            for _ in range(2):
                actual_q = count_questions(ai_response)
                if actual_q <= max_q:
                    break
                question_guard_triggered = True
                ai_response = generate_ai_response(
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
                )
            # финальный аварийный fallback
            if count_questions(ai_response) > max_q:
                question_guard_triggered = True
                ai_response = ai_response.replace("?", ".")

    # Persist AI response to chat table (linked to the user message)
    _user_chat_id = chat_data.data[0]["id"] if chat_data.data else None
    print("AI RESPONSE:", ai_response)
    print("LINKED ID:", _user_chat_id)
    try:
        supabase.table("chat").insert({
            "user_id": message.user_id,
            "pet_id": message.pet_id,
            "message": ai_response,
            "role": "ai",
            "linked_chat_id": _user_chat_id,
        }).execute()
        print("AI INSERT SUCCESS")
    except Exception as _ai_save_err:
        import traceback
        print("[ai_persist ERROR]")
        traceback.print_exc()

    _linked_date = str(date.today()) if decision and structured_data.get("symptom") else None

    response_payload = {
        "chat_saved": chat_data.data,
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
    }

    # --- FINAL ESCALATION MONOTONIC LOCK ---
    # _prev_events already fetched above — reuse to avoid double DB call
    if episode_result.get("episode_id") and decision:
        try:
            apply_monotonic_lock(decision, episode_result["episode_id"], _prev_events)
        except Exception as _mono_err:
            print(f"[monotonic lock] {_mono_err}")
            decision["monotonic_corrected"] = False

    # --- FOLLOW-UP ENGINE v1 ---
    # Pure calculation — no scheduler, no push, no side-effects.
    # Sets follow_up_required and follow_up_window_hours on decision.
    if decision:
        _fu_phase = decision.get("episode_phase", "initial")
        _fu_escalation = decision.get("escalation", "LOW")

        if _fu_phase == "worsening":
            _follow_up_required = True
        elif _fu_phase == "progressing":
            _follow_up_required = True
        elif _fu_phase == "stable" and _fu_escalation in ["HIGH", "CRITICAL"]:
            _follow_up_required = True
        else:
            _follow_up_required = False

        _FOLLOW_UP_WINDOWS = {"CRITICAL": 1, "HIGH": 3, "MODERATE": 8, "LOW": None}
        _follow_up_window_hours = _FOLLOW_UP_WINDOWS.get(_fu_escalation) if _follow_up_required else None

        decision["follow_up_required"] = _follow_up_required
        decision["follow_up_window_hours"] = _follow_up_window_hours
    # ─────────────────────────────────────────────────────────────────────────

    # Persist final triage escalation to episode (monotonic invariant)
    if episode_result.get("episode_id") and decision:
        _ep_final_esc = decision.get("escalation")
        if _ep_final_esc:
            try:
                update_episode_escalation(episode_result["episode_id"], _ep_final_esc)
            except Exception as _ep_esc_err:
                print(f"[episode escalation] {_ep_esc_err}")

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
            "juvenile_adjusted": _juvenile_adjusted,
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
            "cat_anorexia_adjusted": _cat_anorexia_adjusted,
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
    try:
        from routers.timeline import recalculate_day
        from datetime import date as _date_cls
        recalculate_day(pet_id=str(message.pet_id), date_str=str(_date_cls.today()))
    except Exception as _tl_err:
        print(f"[timeline recalc] {_tl_err}")

    return response_payload


@router.get("/events/{pet_id}")
def get_events(pet_id: str):
    response = (
        supabase
        .table("events")
        .select("*")
        .eq("pet_id", pet_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return response.data


@router.get("/medical-events/{pet_id}")
def get_medical_events_endpoint(pet_id: str):
    return get_medical_events(pet_id)



@router.post("/migrate-user")
def migrate_user(body: MigrateUser):
    if body.anonymous_id == body.new_user_id:
        return JSONResponse(
            status_code=400,
            content={"error": "anonymous_id and new_user_id must be different"}
        )

    updated_events = 0
    updated_chat = 0
    updated_pets = 0

    try:
        result = (
            supabase.table("events")
            .update({"user_id": body.new_user_id})
            .eq("user_id", body.anonymous_id)
            .execute()
        )
        updated_events = len(result.data) if result.data else 0
    except Exception as e:
        print(f"[migrate error] events: {e}")

    try:
        result = (
            supabase.table("chat")
            .update({"user_id": body.new_user_id})
            .eq("user_id", body.anonymous_id)
            .execute()
        )
        updated_chat = len(result.data) if result.data else 0
    except Exception as e:
        print(f"[migrate error] chat: {e}")

    try:
        result = (
            supabase.table("pets")
            .update({"user_id": body.new_user_id})
            .eq("user_id", body.anonymous_id)
            .execute()
        )
        updated_pets = len(result.data) if result.data else 0
    except Exception as e:
        print(f"[migrate error] pets: {e}")

    return {
        "status": "migrated",
        "updated_events": updated_events,
        "updated_chat": updated_chat,
        "updated_pets": updated_pets,
    }
