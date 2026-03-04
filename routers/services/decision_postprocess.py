"""
decision_postprocess.py — Post-processing layers extracted from routers/chat.py.
Handles systemic state, species/age multipliers, episode clinical, cat anorexia,
cross-class override, reaction/intent classification, risk engine, response type,
dialogue_mode, episode phase engine, monotonic lock, follow-up engine.
"""

from datetime import datetime, timezone

from routers.services.chat_helpers import (
    escalate_min,
    apply_monotonic_lock,
    compute_episode_phase_v1,
)
from routers.services.risk_engine import calculate_risk_score, ESCALATION_ORDER
from routers.services.clinical_engine import apply_cross_symptom_override
from routers.services.recurrence import check_recurrence
from routers.services.episode_phase import compute_episode_phase


def postprocess_decision(
    decision: dict,
    structured_data: dict,
    message_text: str,
    pet_id: str,
    pet_profile: dict,
    episode_result: dict,
    prev_events: list,
    species: str,
    age_years: float | None,
    lethargy_level: str,
    refusing_water: bool,
    temperature_value: float | None,
    previous_assistant_text: str | None,
    recent_events: list,
    supabase_client,
) -> dict:

    # ── Systemic State Layer v1 ───────────────────────────────────────────────
    _systemic_adjusted = False
    _temp_lethargy_override = False

    # Lethargy model — skipped for RESPIRATORY (lethargy already baked into clinical routing)
    _is_respiratory = isinstance(structured_data, dict) and structured_data.get("symptom_class") == "RESPIRATORY"
    if not _is_respiratory:
        if lethargy_level == "mild":
            _cur = decision["escalation"]
            _idx = ESCALATION_ORDER[_cur]
            _new = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
            if _new != _cur:
                decision["escalation"] = _new
                _systemic_adjusted = True

        elif lethargy_level == "severe":
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

    # GI + refusing_water → CRITICAL (v4.4: raised from HIGH)
    if refusing_water and isinstance(structured_data, dict) and structured_data.get("symptom_class") == "GI":
        _before = decision["escalation"]
        decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        if decision["escalation"] != _before:
            _systemic_adjusted = True

    # GI + severe lethargy → CRITICAL (v4.4)
    if (
        lethargy_level == "severe"
        and isinstance(structured_data, dict)
        and structured_data.get("symptom_class") == "GI"
    ):
        _before = decision["escalation"]
        decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        if decision["escalation"] != _before:
            _systemic_adjusted = True

    # Refusing water + lethargy → min HIGH (v4.3 tightening)
    if refusing_water and lethargy_level != "none":
        _before = decision["escalation"]
        decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
        if decision["escalation"] != _before:
            _systemic_adjusted = True

    # Refusing water + lethargy + GI → CRITICAL (v4.3 tightening)
    if (
        refusing_water
        and lethargy_level != "none"
        and isinstance(structured_data, dict)
        and structured_data.get("symptom_class") == "GI"
    ):
        _before = decision["escalation"]
        decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        if decision["escalation"] != _before:
            _systemic_adjusted = True

    # Temperature escalation (v4.4 recalibrated)
    if isinstance(temperature_value, float):
        _before = decision["escalation"]
        if temperature_value >= 40.0:
            # ≥40 → HIGH; ≥41 already locked CRITICAL by Absolute Critical Layer
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            _systemic_adjusted = True
        elif temperature_value >= 39.7:
            # 39.7–39.9 → MODERATE (v4.4: new threshold)
            decision["escalation"] = escalate_min(decision["escalation"], "MODERATE")
            if decision["escalation"] != _before:
                _systemic_adjusted = True
        elif temperature_value < 37.5:
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            if decision["escalation"] != _before:
                _systemic_adjusted = True

    # Temp + lethargy combined (v4.4: any lethargy + ≥40 → CRITICAL)
    if isinstance(temperature_value, float) and lethargy_level != "none":
        if temperature_value >= 40.0:
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            _systemic_adjusted = True
            _temp_lethargy_override = True
        elif temperature_value >= 39.7:
            _before = decision["escalation"]
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
            if decision["escalation"] != _before:
                _systemic_adjusted = True
            _temp_lethargy_override = True

    decision["lethargy_level"] = lethargy_level
    decision["refusing_water"] = refusing_water
    decision["temperature_value"] = temperature_value
    decision["systemic_adjusted"] = _systemic_adjusted
    decision["temp_lethargy_override"] = _temp_lethargy_override
    # ─────────────────────────────────────────────────────────────────────────

    # ── Species & Age Multipliers ─────────────────────────────────────────────
    _species_adjusted = False
    _age_adjusted = False
    _juvenile_adjusted = False

    # Cat + RESPIRATORY → escalation min HIGH
    if species == "cat" and isinstance(structured_data, dict) and structured_data.get("symptom_class") == "RESPIRATORY":
        _before = decision["escalation"]
        decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
        if decision["escalation"] != _before:
            _species_adjusted = True

    # Cat + difficulty_breathing + lethargy → CRITICAL (v4.2)
    if (
        species == "cat"
        and isinstance(structured_data, dict)
        and structured_data.get("symptom") == "difficulty_breathing"
        and lethargy_level != "none"
    ):
        _before = decision["escalation"]
        decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        if decision["escalation"] != _before:
            _species_adjusted = True

    # Puppy / kitten (age < 1 year) + GI → escalation +1
    if (
        isinstance(age_years, float)
        and age_years < 1
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
        isinstance(age_years, float)
        and age_years < 0.5
        and isinstance(structured_data, dict)
        and structured_data.get("symptom_class") == "GI"
        and (lethargy_level != "none" or refusing_water)
    ):
        _before = decision["escalation"]
        decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        if decision["escalation"] != _before:
            _juvenile_adjusted = True

    # Senior (age >= 10) + systemic_adjusted → escalation +1
    if (
        isinstance(age_years, float)
        and age_years >= 10
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
    _episode_adjusted = False
    _recurrent_flag = False
    _recurrence_adjusted = False

    _ep_id = episode_result.get("episode_id") if isinstance(episode_result, dict) else None
    _ep_symptom = structured_data.get("symptom") if isinstance(structured_data, dict) else None
    _ep_class = structured_data.get("symptom_class") if isinstance(structured_data, dict) else None

    if _ep_id and _ep_symptom:
        # Duration logic
        try:
            _ep_row = (
                supabase_client.table("episodes")
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

                    # Duration escalation — GI (v4.4: species-aware thresholds)
                    if _ep_class == "GI":
                        if isinstance(age_years, float) and age_years < 0.5:
                            # Puppy <6m: ≥6h → HIGH
                            if _episode_duration_hours >= 6:
                                _before = decision["escalation"]
                                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                                if decision["escalation"] != _before:
                                    _episode_adjusted = True
                        elif species == "cat":
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
                        if species == "cat":
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
        compute_episode_phase(_episode_duration_hours)

        # Recurrence Layer — see routers/services/recurrence.py
        _recurrence_adjusted = False
        try:
            _recurrent_flag = check_recurrence(str(pet_id), _ep_symptom)
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
        species == "cat"
        and isinstance(structured_data, dict)
        and structured_data.get("symptom") == "anorexia"
    ):
        _anorexia_duration = decision.get("episode_duration_hours")
        if isinstance(_anorexia_duration, float) and _anorexia_duration >= 24:
            if lethargy_level != "none":
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
    decision["cat_anorexia_adjusted"] = _cat_anorexia_adjusted
    # ─────────────────────────────────────────────────────────────────────────

    # ── Cross-Class Override Layer ────────────────────────────────────────────
    _cross_class_override = False

    _msg_lower = message_text.lower()
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
    user_text = message_text.lower()

    # 1. Repeated symptom detection
    if structured_data.get("symptom") and len(user_text.strip()) < 20:
        _prior_same = any(
            e.get("content", {}).get("symptom") == structured_data.get("symptom")
            for e in recent_events
            if isinstance(e.get("content"), dict)
        )
        if _prior_same:
            reaction_type = "repeated_symptom"

    # 2. Ignored urgent advice
    if decision["escalation"] in ["HIGH", "CRITICAL"]:
        if previous_assistant_text and "ветеринар" in previous_assistant_text.lower():
            if structured_data.get("symptom"):
                reaction_type = "ignored_urgent_advice"

    # 3. Topic shift
    if structured_data.get("symptom") is None and decision["escalation"] in ["HIGH", "CRITICAL"]:
        reaction_type = "topic_shift"

    # 4. Panic detection
    if "!!!" in user_text or "помог" in user_text:
        reaction_type = "panic"

    decision["reaction_type"] = reaction_type

    # Intent classification
    if any(x in _msg_lower for x in [
        "что делать", "что мне делать", "как быть", "помоги", "что теперь",
    ]):
        user_intent = "SEEKING_ACTION"
    elif any(x in _msg_lower for x in [
        "не могу", "нет возможности", "не получится", "далеко",
    ]):
        user_intent = "EXPRESSING_LIMITATION"
    elif any(x in _msg_lower for x in ["снова", "ещё", "опять"]):
        user_intent = "PROVIDING_INFO"
    else:
        user_intent = "NEUTRAL"

    # Constraint detection
    if any(x in _msg_lower for x in [
        "не могу идти", "не могу поехать", "нет клиники", "далеко до ветеринара",
    ]):
        constraint = "no_vet_access"
    else:
        constraint = "none"

    decision["user_intent"] = user_intent
    decision["constraint"] = constraint

    # Cross-symptom risk override
    decision = apply_cross_symptom_override(
        pet_id=pet_id,
        symptom_key=structured_data.get("symptom"),
        decision=decision
    )

    # Risk Engine v1 — parallel scoring, logging only, does NOT affect escalation
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
    decision["dialogue_mode"] = (
        "clinical_escalation"
        if decision["escalation"] in ["MODERATE", "HIGH", "CRITICAL"]
        else "normal"
    )

    # --- EPISODE PHASE ENGINE v1 ---
    _ep_id_for_phase = episode_result.get("episode_id") if isinstance(episode_result, dict) else None
    _phase_prev_max: int | None = None
    if prev_events and _ep_id_for_phase:
        for _pe in prev_events:
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

    # --- FINAL ESCALATION MONOTONIC LOCK ---
    if episode_result.get("episode_id"):
        try:
            apply_monotonic_lock(decision, episode_result["episode_id"], prev_events)
        except Exception as _mono_err:
            print(f"[monotonic lock] {_mono_err}")
            decision["monotonic_corrected"] = False

    # --- FOLLOW-UP ENGINE v1 ---
    # Pure calculation — no scheduler, no push, no side-effects.
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

    return decision
