# symptom_registry_v2.py
# FULL CLINICAL REGISTRY — 85+ symptoms, 11 systems
# Veterinary-calibrated triage data v2.0
# Python 3.9 compatible

from typing import Optional, List, Dict, Any

ESCALATION_ORDER = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def escalate_min(a: str, b: str) -> str:
    """Возвращает более высокий уровень из двух."""
    return a if ESCALATION_ORDER.index(a) >= ESCALATION_ORDER.index(b) else b


# Формат каждого симптома:
# "normalized_key": {
#     "class": str,              # система организма
#     "baseline": str,           # уровень по умолчанию
#     "species_override": dict,  # переопределение по виду {"cat": "HIGH"}
#     "time_thresholds": list,   # [{"hours": N, "species": "cat", "escalation": "HIGH"}]
#     "age_override": dict,      # {"puppy": "MODERATE"}
#     "auto_critical": bool,     # True = CRITICAL без вопросов
#     "clarify_first": str|None, # первый уточняющий вопрос
# }

SYMPTOM_REGISTRY: Dict[str, Any] = {

    # ══════════════════════════════════════════
    # SYSTEMIC (вялость — используется в комбо)
    # ══════════════════════════════════════════

    "lethargy": {
        "class": "SYSTEMIC",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Не встаёт совсем или просто вялый?",
    },
    "severe_lethargy": {
        "class": "SYSTEMIC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Реагирует ли на имя? Может встать?",
    },

    # ══════════════════════════════════════════
    # GI — желудочно-кишечный тракт
    # ══════════════════════════════════════════

    "vomiting": {
        "class": "GI",
        "baseline": "LOW",
        "species_override": {"cat": "MODERATE"},
        "time_thresholds": [
            {"hours": 6,  "species": "puppy",  "escalation": "HIGH"},
            {"hours": 6,  "species": "kitten",  "escalation": "HIGH"},
            {"hours": 12, "species": "all",    "escalation": "MODERATE"},
            {"hours": 12, "species": "cat",    "escalation": "HIGH"},
            {"hours": 24, "species": "dog",    "escalation": "HIGH"},
        ],
        "age_override": {"puppy": "MODERATE", "kitten": "MODERATE"},
        "auto_critical": False,
        "clarify_first": "Сколько раз за последние часы? Пьёт ли воду?",
    },
    "vomiting_water_immediately": {
        "class": "GI",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "vomiting_bile": {
        "class": "GI",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 12, "species": "cat", "escalation": "HIGH"},
            {"hours": 24, "species": "dog", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Натощак или после еды?",
    },
    "vomiting_blood": {
        "class": "GI",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Яркая кровь или тёмная (как кофейная гуща)?",
    },
    "vomiting_coffee_grounds": {
        "class": "GI",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "diarrhea": {
        "class": "GI",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 12, "species": "puppy",  "escalation": "MODERATE"},
            {"hours": 12, "species": "kitten", "escalation": "MODERATE"},
            {"hours": 24, "species": "cat",    "escalation": "MODERATE"},
            {"hours": 48, "species": "dog",    "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Есть ли кровь в стуле?",
    },
    "blood_in_stool": {
        "class": "GI",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Яркая кровь или чёрный дёгтеобразный стул?",
    },
    "melena": {
        "class": "GI",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "anorexia": {
        "class": "GI",
        "baseline": "LOW",
        "species_override": {"cat": "MODERATE"},
        "time_thresholds": [
            {"hours": 12, "species": "puppy",  "escalation": "HIGH"},
            {"hours": 12, "species": "kitten", "escalation": "HIGH"},
            {"hours": 24, "species": "cat",    "escalation": "HIGH"},
            {"hours": 48, "species": "cat",    "escalation": "CRITICAL"},
            {"hours": 48, "species": "dog",    "escalation": "MODERATE"},
            {"hours": 72, "species": "dog",    "escalation": "HIGH"},
        ],
        "auto_critical": False,
        "clarify_first": "Пьёт ли воду? Сколько часов не ест?",
    },
    "abdominal_distension": {
        "class": "GI",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Живот вздулся резко? Пытается рвать но не может?",
    },
    "gdv_pattern": {
        "class": "GI",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "dehydration": {
        "class": "GI",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Пьёт ли воду? Когда последний раз мочился?",
    },
    "refusing_water": {
        "class": "GI",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Сколько часов не пьёт?",
    },
    "constipation": {
        "class": "GI",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 48, "species": "cat", "escalation": "MODERATE"},
            {"hours": 72, "species": "dog", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Пытается ходить в туалет? Есть ли боль?",
    },
    "bloating": {
        "class": "GI",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Крупная порода? Живот напряжён?",
    },
    "pancreatitis_suspected": {
        "class": "GI",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Ела ли жирное? Есть ли боль при касании живота?",
    },
    "jaundice": {
        "class": "GI",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Пожелтели ли дёсны или белки глаз?",
    },

    # ══════════════════════════════════════════
    # RESP — дыхательная система
    # ══════════════════════════════════════════

    "cough": {
        "class": "RESP",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 72, "species": "all", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Есть ли одышка? Влажный или сухой кашель?",
    },
    "dyspnea": {
        "class": "RESP",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Дышит ртом? Дышит животом?",
    },
    "open_mouth_breathing_cat": {
        "class": "RESP",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "respiratory_rate_high": {
        "class": "RESP",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Считали в покое? Более 40 вдохов в минуту?",
    },
    "respiratory_rate_critical": {
        "class": "RESP",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "stridor": {
        "class": "RESP",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Шумный вдох или выдох?",
    },
    "cyanosis": {
        "class": "RESP",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "labored_breathing": {
        "class": "RESP",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Видно ли движение живота при дыхании?",
    },
    "neck_extended_breathing": {
        "class": "RESP",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "cannot_lie_down_breathing": {
        "class": "RESP",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Как давно не ложится? Ночью хуже?",
    },

    # ══════════════════════════════════════════
    # URINARY — мочевыделительная система
    # ══════════════════════════════════════════

    "urinary_straining": {
        "class": "URINARY",
        "baseline": "HIGH",
        "species_override": {"cat": "HIGH"},
        "time_thresholds": [
            {"hours": 12, "species": "cat", "escalation": "CRITICAL"},
            {"hours": 4,  "species": "dog", "escalation": "HIGH"},
            {"hours": 12, "species": "dog", "escalation": "CRITICAL"},
        ],
        "auto_critical": False,
        "clarify_first": "Есть ли хоть капли мочи? Сколько часов без мочи?",
    },
    "urinary_no_output": {
        "class": "URINARY",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "urinary_frequent_small": {
        "class": "URINARY",
        "baseline": "MODERATE",
        "species_override": {"cat": "HIGH"},
        "auto_critical": False,
        "clarify_first": "Это кот? Есть ли кровь в моче?",
    },
    "blood_in_urine": {
        "class": "URINARY",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Есть ли затруднения при мочеиспускании?",
    },
    "urinary_crying_in_litter": {
        "class": "URINARY",
        "baseline": "CRITICAL",
        "auto_critical": False,
        "clarify_first": "Кот или кошка? Есть ли моча в лотке?",
    },
    "incontinence": {
        "class": "URINARY",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Внезапно появилось? Есть ли слабость задних лап?",
    },
    "polyuria": {
        "class": "URINARY",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 72, "species": "all", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Пьёт ли больше обычного?",
    },

    # ══════════════════════════════════════════
    # NEURO — неврологическая система
    # ══════════════════════════════════════════

    "seizure_short": {
        "class": "NEURO",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Сколько длилась? Полностью восстановился?",
    },
    "seizure_long": {
        "class": "NEURO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "seizure_cluster": {
        "class": "NEURO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "ataxia": {
        "class": "NEURO",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Шатается или падает? Как давно?",
    },
    "head_tilt": {
        "class": "NEURO",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Есть ли движения глаз из стороны в сторону?",
    },
    "collapse": {
        "class": "NEURO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "paralysis_acute": {
        "class": "NEURO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "hind_limb_weakness": {
        "class": "NEURO",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Двигает ли задними лапами? Была ли травма?",
    },
    "sudden_blindness": {
        "class": "NEURO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "loss_of_consciousness": {
        "class": "NEURO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "disorientation": {
        "class": "NEURO",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Как давно? Была ли травма головы?",
    },
    "nystagmus": {
        "class": "NEURO",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли наклон головы или рвота?",
    },

    # ══════════════════════════════════════════
    # CARDIAC — сердечно-сосудистая система
    # ══════════════════════════════════════════

    "syncope": {
        "class": "CARDIAC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "tachycardia_resting": {
        "class": "CARDIAC",
        "baseline": "MODERATE",
        "time_thresholds": [
            {"hours": 0.5, "species": "all", "escalation": "HIGH"},
        ],
        "auto_critical": False,
        "clarify_first": "В покое измеряли? Есть ли слабость или шаткость?",
    },
    "tachycardia_severe_large_dog": {
        "class": "CARDIAC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли слабость или потеря сознания?",
    },
    "tachycardia_severe_small_dog": {
        "class": "CARDIAC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли слабость или одышка?",
    },
    "tachycardia_severe_cat": {
        "class": "CARDIAC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли одышка или слабость?",
    },
    "ascites_suspected": {
        "class": "CARDIAC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Живот увеличился быстро (за дни)?",
    },
    "cardiac_cough": {
        "class": "CARDIAC",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Кашляет ночью? После нагрузки?",
    },
    "exercise_intolerance": {
        "class": "CARDIAC",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Резко появилось? Есть ли одышка в покое?",
    },
    "orthopnea": {
        "class": "CARDIAC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Не может лечь? Ночная одышка?",
    },
    "rapid_weight_gain": {
        "class": "CARDIAC",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "За сколько дней набрал? Есть ли одышка?",
    },
    "visible_heartbeat": {
        "class": "CARDIAC",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Есть ли слабость или одышка?",
    },

    # ══════════════════════════════════════════
    # OPHTHALMIC — глаза
    # ══════════════════════════════════════════

    "red_eye": {
        "class": "OPHTHALMIC",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 48, "species": "all", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Щурится ли питомец?",
    },
    "ocular_discharge": {
        "class": "OPHTHALMIC",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 72, "species": "all", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Один глаз или оба?",
    },
    "squinting_eye_pain": {
        "class": "OPHTHALMIC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Держит ли глаз закрытым постоянно?",
    },
    "sudden_blindness_eye": {
        "class": "OPHTHALMIC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "enlarged_globe": {
        "class": "OPHTHALMIC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "corneal_opacity": {
        "class": "OPHTHALMIC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Было ли повреждение глаза?",
    },
    "prolapsed_eye": {
        "class": "OPHTHALMIC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },

    # ══════════════════════════════════════════
    # DERM — кожа и аллергия
    # ══════════════════════════════════════════

    "local_rash": {
        "class": "DERM",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 72, "species": "all", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Есть ли зуд?",
    },
    "severe_pruritus": {
        "class": "DERM",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Есть ли отёк морды?",
    },
    "facial_swelling": {
        "class": "DERM",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли рвота или затруднённое дыхание?",
    },
    "hives_generalized": {
        "class": "DERM",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли вялость или одышка?",
    },
    "anaphylaxis_suspected": {
        "class": "DERM",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "skin_necrosis": {
        "class": "DERM",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Были ли ожоги или химические контакты?",
    },
    "wound_bleeding": {
        "class": "DERM",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Кровотечение остановилось или продолжается?",
    },
    "active_bleeding": {
        "class": "DERM",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },

    # ══════════════════════════════════════════
    # MUSCULO — опорно-двигательный аппарат
    # ══════════════════════════════════════════

    "mild_lameness": {
        "class": "MUSCULO",
        "baseline": "LOW",
        "time_thresholds": [
            {"hours": 48, "species": "all", "escalation": "MODERATE"},
        ],
        "auto_critical": False,
        "clarify_first": "Наступает ли на лапу?",
    },
    "non_weight_bearing": {
        "class": "MUSCULO",
        "baseline": "MODERATE",
        "time_thresholds": [
            {"hours": 24, "species": "all", "escalation": "HIGH"},
        ],
        "auto_critical": False,
        "clarify_first": "Полностью не опирается? Есть ли отёк?",
    },
    "severe_pain_movement": {
        "class": "MUSCULO",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Кричит при прикосновении?",
    },
    "paralysis_limb": {
        "class": "MUSCULO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "cannot_stand": {
        "class": "MUSCULO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "trauma_hit_by_car": {
        "class": "MUSCULO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "dragging_hind_legs": {
        "class": "MUSCULO",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "pain_on_touch": {
        "class": "MUSCULO",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Где именно боль? Была ли травма?",
    },

    # ══════════════════════════════════════════
    # TEMP — температура тела
    # ══════════════════════════════════════════

    "fever_mild": {
        "class": "TEMP",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Есть ли вялость или отказ от еды?",
    },
    "fever_high": {
        "class": "TEMP",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли вялость?",
    },
    "fever_critical": {
        "class": "TEMP",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "hypothermia": {
        "class": "TEMP",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Ниже 37.5 градусов? Есть ли вялость?",
    },
    "hypothermia_severe": {
        "class": "TEMP",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "heatstroke": {
        "class": "TEMP",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },

    # ══════════════════════════════════════════
    # TOXIC — отравления
    # ══════════════════════════════════════════

    "xylitol_ingestion": {
        "class": "TOXIC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "antifreeze_ingestion": {
        "class": "TOXIC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "rodenticide_ingestion": {
        "class": "TOXIC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Когда это произошло? Сколько съел?",
    },
    "lily_ingestion_cat": {
        "class": "TOXIC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "battery_ingestion": {
        "class": "TOXIC",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "medication_overdose": {
        "class": "TOXIC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Какой препарат и сколько?",
    },
    "chocolate_ingestion": {
        "class": "TOXIC",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Тёмный или молочный шоколад? Сколько и какой вес собаки?",
    },
    "grape_raisin_ingestion": {
        "class": "TOXIC",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Сколько съел? Есть ли рвота?",
    },
    "onion_garlic_ingestion": {
        "class": "TOXIC",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Сколько и как давно?",
    },

    # ══════════════════════════════════════════
    # INGESTION — механические инородные тела
    # ══════════════════════════════════════════

    "plastic_swallowed": {
        "class": "INGESTION",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Какого размера предмет? Есть ли рвота?",
    },
    "bone_swallowed": {
        "class": "INGESTION",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Сырая или варёная кость? Есть ли рвота?",
    },
    "string_thread_swallowed": {
        "class": "INGESTION",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "toy_swallowed": {
        "class": "INGESTION",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли рвота или вялость?",
    },
    "sharp_object_swallowed": {
        "class": "INGESTION",
        "baseline": "CRITICAL",
        "auto_critical": True,
        "clarify_first": None,
    },
    "large_package_swallowed": {
        "class": "INGESTION",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли вздутие живота?",
    },
    "coin_swallowed": {
        "class": "INGESTION",
        "baseline": "MODERATE",
        "auto_critical": False,
        "clarify_first": "Какой размер монеты? Есть ли рвота?",
    },
    "sock_clothing_swallowed": {
        "class": "INGESTION",
        "baseline": "HIGH",
        "auto_critical": False,
        "clarify_first": "Есть ли рвота? Ест ли?",
    },
}
