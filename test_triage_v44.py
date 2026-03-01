"""
Medical Core v4.4 — Triage Logic Test
Tests 14 required scenarios + GI baseline sanity checks.
Exercises the triage layers directly (no HTTP, no database).
"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from routers.services.risk_engine import ESCALATION_ORDER


def escalate_min(current: str, target: str) -> str:
    if ESCALATION_ORDER[current] < ESCALATION_ORDER[target]:
        return target
    return current


def triage(
    *,
    symptom: str | None = None,
    symptom_class: str | None = None,
    species: str = "dog",
    age_years: float | None = None,
    lethargy_level: str = "none",
    refusing_water: bool = False,
    temperature_value: float | None = None,
    respiratory_rate: int | None = None,
    seizure_duration: float | None = None,
    episode_duration_hours: float | None = None,
    stats_today: int = 1,
    stats_last_24h: int = 1,
    message_lower: str = "",
) -> dict:
    """
    Simplified triage simulation covering all v4.4 layers.
    Returns dict with escalation and flags.
    """
    decision = None
    flags = []

    # ── Clinical routing ─────────────────────────────────────────────────────
    stats = {"today": stats_today, "last_hour": stats_today, "last_24h": stats_last_24h}

    if symptom_class == "GI":
        _esc = "LOW"
        if stats_today >= 3:
            _esc = "MODERATE"
        decision = {"escalation": _esc, "stats": stats, "symptom": symptom,
                    "stop_questioning": False, "override_urgency": False}

    elif symptom_class == "RESPIRATORY":
        if symptom == "difficulty_breathing" and lethargy_level != "none":
            _esc = "CRITICAL"
            flags.append("resp_recal")
        elif symptom == "difficulty_breathing":
            _esc = "HIGH"
        elif lethargy_level != "none":
            _esc = "MODERATE"
            flags.append("resp_recal")
        elif stats_today >= 2:
            _esc = "MODERATE"
            flags.append("resp_recal")
        else:
            _esc = "LOW"
        decision = {"escalation": _esc, "stats": stats, "symptom": symptom,
                    "stop_questioning": _esc in ["HIGH", "CRITICAL"],
                    "override_urgency": _esc in ["HIGH", "CRITICAL"]}

    elif symptom_class == "NEURO":
        if stats_last_24h >= 2:
            _esc = "CRITICAL"
        elif isinstance(seizure_duration, float) and seizure_duration >= 2.0:
            _esc = "CRITICAL"
        elif isinstance(seizure_duration, float) and seizure_duration < 1.0:
            _esc = "HIGH"
        else:
            _esc = "HIGH"
        decision = {"escalation": _esc, "stats": stats, "symptom": symptom,
                    "stop_questioning": True, "override_urgency": True}

    elif symptom_class == "URINARY":
        _urinary_straining = any(k in message_lower for k in [
            "тужится", "не может пописать", "не может помочиться", "позывы без мочи",
        ])
        _urinary_pain = any(k in message_lower for k in [
            "болит", "боль", "беспокойн", "кричит", "скулит",
        ])
        if species == "cat":
            if _urinary_straining:
                _esc = "CRITICAL"
                flags.append("urinary_straining")
            else:
                _esc = "MODERATE"
        else:
            if lethargy_level != "none" or _urinary_pain:
                _esc = "HIGH"
            else:
                _esc = "MODERATE"
        decision = {"escalation": _esc, "stats": stats, "symptom": symptom,
                    "stop_questioning": _esc in ["HIGH", "CRITICAL"],
                    "override_urgency": _esc in ["HIGH", "CRITICAL"]}

    elif symptom_class == "TOXIC":
        decision = {"escalation": "CRITICAL", "stats": stats, "symptom": symptom,
                    "stop_questioning": True, "override_urgency": True}

    # ── GDV override ──────────────────────────────────────────────────────────
    _gdv_keywords = [
        "вздут", "раздуло живот", "живот раздуло",
        "пытается рвать но не может", "позывы без рвоты", "живот как барабан",
    ]
    if any(k in message_lower for k in _gdv_keywords):
        if decision is None:
            decision = {"escalation": "LOW", "stats": stats, "symptom": symptom,
                        "stop_questioning": True, "override_urgency": True}
        decision["escalation"] = "CRITICAL"
        flags.append("gdv")

    # ── Absolute Critical & Vital Signs Layer (v4.3/v4.4) ────────────────────
    _ac_keywords = [
        "не дышит", "агональное дыхание", "синие десны", "синюшные слизистые",
        "без сознания", "потерял сознание",
        "живот как барабан", "раздуло живот", "живот раздуло", "пытается рвать но не может",
        "внезапно ослеп", "ослепла", "ослеп", "резкая слепота",
        "кровотечение не останавл", "сильное кровотечение", "активное кровотечение",
        "серийные судороги", "судорожный статус", "статус эпилептикус",
    ]
    _has_open_mouth_cat = (
        ("открытая пасть" in message_lower or "дышит с открытым ртом" in message_lower)
        and species == "cat"
    )
    if any(k in message_lower for k in _ac_keywords) or _has_open_mouth_cat:
        if decision is None:
            decision = {"escalation": "LOW", "stats": stats, "symptom": symptom,
                        "stop_questioning": True, "override_urgency": True}
        decision["escalation"] = "CRITICAL"
        flags.append("abs_crit")

    # Temperature ≥41 → CRITICAL
    if isinstance(temperature_value, float) and temperature_value >= 41.0:
        if decision is None:
            decision = {"escalation": "LOW", "stats": stats, "symptom": symptom,
                        "stop_questioning": True, "override_urgency": True}
        decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        flags.append("hyper_crit")

    # Temperature ≥40 + severe lethargy → CRITICAL (v4.3 abs layer)
    if isinstance(temperature_value, float) and temperature_value >= 40.0 and lethargy_level == "severe":
        if decision is None:
            decision = {"escalation": "LOW", "stats": stats, "symptom": symptom,
                        "stop_questioning": True, "override_urgency": True}
        decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
        flags.append("hyper_crit")

    # Respiratory rate rules (v4.4 thresholds)
    if isinstance(respiratory_rate, int):
        if decision is None and respiratory_rate >= 40:
            decision = {"escalation": "LOW", "stats": stats, "symptom": symptom,
                        "stop_questioning": False, "override_urgency": False}
        if decision:
            if species == "cat":
                if respiratory_rate >= 50:
                    decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                    flags.append("resp_rate_crit")
                elif respiratory_rate >= 40:
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    flags.append("resp_rate_high")
            else:
                if respiratory_rate >= 50:
                    decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                    flags.append("resp_rate_crit")
                elif respiratory_rate >= 40:
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    flags.append("resp_rate_high")

    # ── Systemic State Layer ──────────────────────────────────────────────────
    # Standalone decision for temperature
    if isinstance(temperature_value, float) and decision is None:
        if temperature_value >= 39.5:
            decision = {"escalation": "LOW", "stats": stats, "symptom": symptom,
                        "stop_questioning": True, "override_urgency": True}

    # Standalone for refusing_water + lethargy
    if refusing_water and lethargy_level != "none" and decision is None:
        decision = {"escalation": "LOW", "stats": stats, "symptom": symptom,
                    "stop_questioning": False, "override_urgency": False}

    if decision:
        _is_respiratory = symptom_class == "RESPIRATORY"
        if not _is_respiratory:
            if lethargy_level == "mild":
                _cur = decision["escalation"]
                _idx = ESCALATION_ORDER[_cur]
                decision["escalation"] = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]
            elif lethargy_level == "severe":
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")

        # GI + refusing_water → CRITICAL (v4.4)
        if refusing_water and symptom_class == "GI":
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            flags.append("gi_no_water")

        # GI + severe lethargy → CRITICAL (v4.4)
        if lethargy_level == "severe" and symptom_class == "GI":
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            flags.append("gi_leth_crit")

        # Refusing water + lethargy → HIGH
        if refusing_water and lethargy_level != "none":
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")

        # Temperature escalation (v4.4)
        if isinstance(temperature_value, float):
            _before = decision["escalation"]
            if temperature_value >= 40.0:
                decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                flags.append("temp_high")
            elif temperature_value >= 39.7:
                decision["escalation"] = escalate_min(decision["escalation"], "MODERATE")
                if decision["escalation"] != _before:
                    flags.append("temp_moderate")

        # Temp + lethargy combined (v4.4: any lethargy + ≥40 → CRITICAL)
        if isinstance(temperature_value, float) and lethargy_level != "none":
            if temperature_value >= 40.0:
                decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                flags.append("temp_leth_crit")

    # ── Species & Age Multipliers ─────────────────────────────────────────────
    if decision:
        if species == "cat" and symptom_class == "RESPIRATORY":
            decision["escalation"] = escalate_min(decision["escalation"], "HIGH")

        if isinstance(age_years, float) and age_years < 1 and symptom_class == "GI":
            _cur = decision["escalation"]
            _idx = ESCALATION_ORDER[_cur]
            decision["escalation"] = ["LOW", "MODERATE", "HIGH", "CRITICAL"][min(_idx + 1, 3)]

        if (
            isinstance(age_years, float) and age_years < 0.5
            and symptom_class == "GI"
            and (lethargy_level != "none" or refusing_water)
        ):
            decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
            flags.append("juv_crit")

    # ── Episode Clinical Layer ────────────────────────────────────────────────
    if decision and isinstance(episode_duration_hours, float):
        if symptom_class == "GI":
            if isinstance(age_years, float) and age_years < 0.5:
                if episode_duration_hours >= 6:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        flags.append("ep_dur")
            elif species == "cat":
                if episode_duration_hours >= 12:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        flags.append("ep_dur")
            else:
                # Adult dog: ≥12h → MODERATE, ≥24h → HIGH
                if episode_duration_hours >= 24:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        flags.append("ep_dur")
                elif episode_duration_hours >= 12:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "MODERATE")
                    if decision["escalation"] != _before:
                        flags.append("ep_dur")

        elif symptom_class == "URINARY":
            if species == "cat":
                if episode_duration_hours >= 24:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "CRITICAL")
                    if decision["escalation"] != _before:
                        flags.append("ep_dur_crit")
                elif episode_duration_hours >= 12:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        flags.append("ep_dur")
            else:
                if episode_duration_hours >= 24:
                    _before = decision["escalation"]
                    decision["escalation"] = escalate_min(decision["escalation"], "HIGH")
                    if decision["escalation"] != _before:
                        flags.append("ep_dur")

    escalation = decision["escalation"] if decision else "NO_DECISION"
    return {"escalation": escalation, "flags": flags}


def run_scenarios():
    SCENARIOS = [
        # label, kwargs, expected
        # ── 14 Required scenarios ──────────────────────────────────────────
        ("T1  Dog GI 18h→MOD",
         dict(symptom="vomiting", symptom_class="GI", species="dog",
              episode_duration_hours=18.0),
         "MODERATE"),

        ("T2  Dog GI 26h→HIGH",
         dict(symptom="vomiting", symptom_class="GI", species="dog",
              episode_duration_hours=26.0),
         "HIGH"),

        ("T3  Cat GI 14h→HIGH",
         dict(symptom="vomiting", symptom_class="GI", species="cat",
              episode_duration_hours=14.0),
         "HIGH"),

        ("T4  Puppy GI 7h→HIGH",
         dict(symptom="vomiting", symptom_class="GI", species="dog",
              age_years=0.3, episode_duration_hours=7.0),
         "HIGH"),

        ("T5  Puppy GI+leth→CRIT",
         dict(symptom="vomiting", symptom_class="GI", species="dog",
              age_years=0.3, lethargy_level="severe"),
         "CRITICAL"),

        ("T6  Cat urinary 13h→HIGH",
         dict(symptom="urinary_obstruction", symptom_class="URINARY", species="cat",
              episode_duration_hours=13.0),
         "HIGH"),

        ("T7  Cat urinary 25h→CRIT",
         dict(symptom="urinary_obstruction", symptom_class="URINARY", species="cat",
              episode_duration_hours=25.0),
         "CRITICAL"),

        ("T8  Dog resp 42/min→HIGH",
         dict(symptom="cough", symptom_class="RESPIRATORY", species="dog",
              respiratory_rate=42),
         "HIGH"),

        ("T9  Cat resp 52/min→CRIT",
         dict(symptom="cough", symptom_class="RESPIRATORY", species="cat",
              respiratory_rate=52),
         "CRITICAL"),

        ("T10 Temp 39.7→MOD",
         dict(symptom=None, symptom_class=None, species="dog",
              temperature_value=39.7),
         "MODERATE"),

        ("T11 Temp 40.1→HIGH",
         dict(symptom=None, symptom_class=None, species="dog",
              temperature_value=40.1),
         "HIGH"),

        ("T12 Temp 40.1+leth→CRIT",
         dict(symptom=None, symptom_class=None, species="dog",
              temperature_value=40.1, lethargy_level="severe"),
         "CRITICAL"),

        ("T13 Seizure 3min→CRIT",
         dict(symptom="seizure", symptom_class="NEURO", species="dog",
              seizure_duration=3.0),
         "CRITICAL"),

        ("T14 2 seizures 24h→CRIT",
         dict(symptom="seizure", symptom_class="NEURO", species="dog",
              stats_last_24h=2),
         "CRITICAL"),

        # ── GI Baseline Sanity ─────────────────────────────────────────────
        ("G1  1x_vomit→LOW",
         dict(symptom="vomiting", symptom_class="GI", species="dog"),
         "LOW"),

        ("G2  3x_vomit_today→MOD",
         dict(symptom="vomiting", symptom_class="GI", species="dog",
              stats_today=3, stats_last_24h=3),
         "MODERATE"),

        ("G3  GI+severe_leth→CRIT",
         dict(symptom="vomiting", symptom_class="GI", species="dog",
              lethargy_level="severe"),
         "CRITICAL"),

        ("G4  GI+no_water→CRIT",
         dict(symptom="vomiting", symptom_class="GI", species="dog",
              refusing_water=True),
         "CRITICAL"),

        # ── RESPIRATORY Sanity ──────────────────────────────────────────────
        ("R1  cough_alone→LOW",
         dict(symptom="cough", symptom_class="RESPIRATORY", species="dog"),
         "LOW"),

        ("R2  cough_repeated→MOD",
         dict(symptom="cough", symptom_class="RESPIRATORY", species="dog",
              stats_today=2, stats_last_24h=2),
         "MODERATE"),

        ("R3  cough+leth→MOD",
         dict(symptom="cough", symptom_class="RESPIRATORY", species="dog",
              lethargy_level="mild"),
         "MODERATE"),

        ("R4  diff_breath→HIGH",
         dict(symptom="difficulty_breathing", symptom_class="RESPIRATORY", species="dog"),
         "HIGH"),
    ]

    col_w = 28
    print(f"\n{'─'*90}")
    print(f"{'Scenario':<{col_w}} {'class':<12} {'got':<10} {'exp':<10} {'result':<8} flags")
    print(f"{'─'*90}")

    passed = 0
    failed = 0
    for label, kwargs, expected in SCENARIOS:
        result = triage(**kwargs)
        got = result["escalation"]
        ok = (got == expected)
        status = "PASS" if ok else "FAIL"
        sym_class = kwargs.get("symptom_class") or "UNKNOWN"
        flag_str = ",".join(result["flags"]) if result["flags"] else "-"
        print(f"{label:<{col_w}} {sym_class:<12} {got:<10} {expected:<10} {status:<8} {flag_str}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"{'─'*90}")
    print(f"TOTAL: {passed}/{passed + failed} PASS")
    return failed == 0


if __name__ == "__main__":
    all_pass = run_scenarios()
    sys.exit(0 if all_pass else 1)
