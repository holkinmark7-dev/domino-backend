"""
clinical_router.py — Clinical decision logic extracted from routers/chat.py.
Handles symptom-class routing, red flag fallback, blood/GDV overrides,
absolute critical & vital signs layer.
"""

from routers.services.chat_helpers import escalate_min
from routers.services.clinical_engine import (
    get_symptom_stats,
    build_clinical_decision,
    apply_cross_symptom_override,
)
from routers.services.risk_engine import ESCALATION_ORDER
from routers.services.memory import get_medical_events


def build_full_clinical_decision(
    message_text: str,
    pet_id: str,
    structured_data: dict,
    pet_profile: dict,
    episode_result: dict,
    red_flag: bool,
    lethargy_level: str,
    temperature_value: float | None,
    respiratory_rate: int | None,
    seizure_duration: float | None,
    species: str,
    age_years: float | None,
    prev_events: list | None = None,
) -> dict | None:
    decision = None
    _blood_type_adjusted = False
    _respiratory_recalibrated = False
    _respiratory_adjusted = False
    _vital_override_triggered = False

    if structured_data.get("symptom_class") == "GI":
        stats = get_symptom_stats(
            pet_id=pet_id,
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
        previous_events = prev_events if prev_events is not None else get_medical_events(pet_id=pet_id, limit=20)

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
            pet_id=pet_id,
            symptom_key=structured_data.get("symptom")
        )

        # Explicit side-effect — current episode
        stats["today"] += 1
        stats["last_hour"] += 1
        stats["last_24h"] += 1

        symptom = structured_data.get("symptom")

        # difficulty_breathing + lethargy → CRITICAL
        if symptom == "difficulty_breathing" and lethargy_level != "none":
            _esc = "CRITICAL"
            _respiratory_recalibrated = True
        # difficulty_breathing alone → HIGH
        elif symptom == "difficulty_breathing":
            _esc = "HIGH"
        # cough/sneezing + lethargy → MODERATE
        elif lethargy_level != "none":
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
        stats = get_symptom_stats(pet_id=pet_id, symptom_key=symptom)
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
        stats = get_symptom_stats(pet_id=pet_id, symptom_key=symptom)
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
        stats = get_symptom_stats(pet_id=pet_id, symptom_key=symptom)
        stats["today"] += 1
        stats["last_hour"] += 1
        stats["last_24h"] += 1

        # ≥2 seizures in 24h → CRITICAL
        if stats.get("last_24h", 0) >= 2:
            _esc = "CRITICAL"
        # seizure_duration ≥2 min → CRITICAL
        elif isinstance(seizure_duration, float) and seizure_duration >= 2.0:
            _esc = "CRITICAL"
        # single seizure <1 min → HIGH
        elif isinstance(seizure_duration, float) and seizure_duration < 1.0:
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
        stats = get_symptom_stats(pet_id=pet_id, symptom_key=symptom)
        stats["today"] += 1
        stats["last_hour"] += 1
        stats["last_24h"] += 1

        _urinary_msg = message_text.lower()
        _urinary_straining = any(k in _urinary_msg for k in [
            "тужится", "не может пописать", "не может помочиться", "позывы без мочи",
        ])
        _urinary_pain = any(k in _urinary_msg for k in [
            "болит", "боль", "беспокойн", "кричит", "скулит",
        ])

        if species == "cat":
            if _urinary_straining:
                _esc = "CRITICAL"
            else:
                _esc = "MODERATE"  # duration escalation handled in Episode Clinical Layer
        else:  # dog
            if lethargy_level != "none" or _urinary_pain:
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
        stats = get_symptom_stats(pet_id=pet_id, symptom_key=symptom)
        stats["today"] += 1
        stats["last_hour"] += 1
        stats["last_24h"] += 1

        # Base escalation by symptom
        if symptom == "fever":
            _esc = "MODERATE"
        elif symptom in ["weakness", "lethargy"]:
            _esc = "LOW" if lethargy_level == "mild" else "MODERATE"
        elif symptom == "anorexia":
            # anorexia + severe lethargy → HIGH
            if lethargy_level == "severe":
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
    _gdv_msg = message_text.lower()
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

    _ac_msg = message_text.lower()

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
        and species == "cat"
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
    if isinstance(temperature_value, float) and temperature_value >= 41.0:
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
        isinstance(temperature_value, float)
        and temperature_value >= 40.0
        and lethargy_level == "severe"
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
    if isinstance(respiratory_rate, int):
        # Create standalone decision if needed
        if decision is None and respiratory_rate >= 40:
            decision = {
                "escalation": "LOW",
                "stats": {"today": 0, "last_hour": 0, "last_24h": 0},
                "symptom": structured_data.get("symptom") if isinstance(structured_data, dict) else None,
                "stop_questioning": False,
                "override_urgency": False,
            }
        if decision:
            if species == "cat":
                if respiratory_rate >= 50:  # v4.4: lowered from >50 to >=50
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                        _vital_override_triggered = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
                elif respiratory_rate >= 40:  # v4.4: lowered from >40 to >=40
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
            else:  # dog and other species
                if respiratory_rate >= 50:  # v4.4: lowered from >50 to >=50
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                        _vital_override_triggered = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
                elif respiratory_rate >= 40:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        _respiratory_adjusted = True
                    decision["stop_questioning"] = True
                    decision["override_urgency"] = True
    # ─────────────────────────────────────────────────────────────────────────

    # Attach debug flags to decision dict
    if decision is not None:
        decision.setdefault("blood_type_adjusted", _blood_type_adjusted)
        decision.setdefault("respiratory_recalibrated", _respiratory_recalibrated)
        decision.setdefault("respiratory_adjusted", _respiratory_adjusted)
        decision.setdefault("vital_override_triggered", _vital_override_triggered)

    return decision
