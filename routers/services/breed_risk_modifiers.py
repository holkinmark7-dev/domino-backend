# breed_risk_modifiers.py
# Модификаторы риска на основе породы и веса питомца
# Применяется ПОСЛЕ базового triage — только повышает escalation
# Python 3.9 compatible

from typing import Optional, List, Dict, Tuple

ESCALATION_ORDER = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


def escalate_min(a: str, b: str) -> str:
    """Возвращает более высокий уровень из двух."""
    return a if ESCALATION_ORDER.index(a) >= ESCALATION_ORDER.index(b) else b


# ──────────────────────────────────────────────────────────────────
# BREED_RISK_MAP
# Ключ: нормализованное название породы (lowercase)
# Значение: список правил {"symptoms": [...], "escalation": str, "reason": str}
# ──────────────────────────────────────────────────────────────────

BREED_RISK_MAP: Dict[str, List[Dict]] = {

    # ── ТАКСА (IVDD — межпозвоночные диски) ──────────────────────
    "dachshund": [
        {
            "symptoms": ["hind_limb_weakness"],
            "escalation": "HIGH",
            "reason": "Такса — высокий риск IVDD (грыжа диска)",
        },
        {
            "symptoms": ["pain_on_touch"],
            "escalation": "HIGH",
            "reason": "Такса — боль при прикосновении может указывать на IVDD",
        },
        {
            "symptoms": ["dragging_hind_legs"],
            "escalation": "CRITICAL",
            "reason": "Такса + волочение задних лап = экстренная неврология",
        },
        {
            "symptoms": ["ataxia"],
            "escalation": "HIGH",
            "reason": "Такса — атаксия с высоким риском IVDD",
        },
    ],
    "такса": [  # русское написание
        {
            "symptoms": ["hind_limb_weakness"],
            "escalation": "HIGH",
            "reason": "Такса — высокий риск IVDD (грыжа диска)",
        },
        {
            "symptoms": ["pain_on_touch"],
            "escalation": "HIGH",
            "reason": "Такса — боль при прикосновении может указывать на IVDD",
        },
        {
            "symptoms": ["dragging_hind_legs"],
            "escalation": "CRITICAL",
            "reason": "Такса + волочение задних лап = экстренная неврология",
        },
    ],

    # ── БРАХИЦЕФАЛЫ (дыхательный синдром) ────────────────────────
    "bulldog": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Бульдог — брахицефальный синдром, одышка опасна",
        },
        {
            "symptoms": ["labored_breathing"],
            "escalation": "HIGH",
            "reason": "Бульдог — затруднённое дыхание при BOAS",
        },
        {
            "symptoms": ["open_mouth_breathing_cat"],
            "escalation": "CRITICAL",
            "reason": "Бульдог + дыхание ртом = критическая обструкция",
        },
    ],
    "бульдог": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Бульдог — брахицефальный синдром, одышка опасна",
        },
        {
            "symptoms": ["labored_breathing"],
            "escalation": "HIGH",
            "reason": "Бульдог — затруднённое дыхание при BOAS",
        },
    ],
    "pug": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Мопс — брахицефальный синдром, одышка опасна",
        },
        {
            "symptoms": ["labored_breathing"],
            "escalation": "HIGH",
            "reason": "Мопс — затруднённое дыхание при BOAS",
        },
    ],
    "мопс": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Мопс — брахицефальный синдром, одышка опасна",
        },
    ],
    "french bulldog": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Французский бульдог — брахицефальный синдром",
        },
    ],
    "французский бульдог": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Французский бульдог — брахицефальный синдром",
        },
    ],
    "shih tzu": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Ши-тцу — брахицефальный синдром",
        },
    ],
    "ши-тцу": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Ши-тцу — брахицефальный синдром",
        },
    ],
    "boston terrier": [
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Бостон-терьер — брахицефальный синдром",
        },
    ],

    # ── КАРДИО ПОРОДЫ (HCM и DCM) ─────────────────────────────────
    "maine coon": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Мейн-кун — высокий риск HCM (гипертрофическая кардиомиопатия)",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Мейн-кун — одышка при HCM требует срочной кардиологии",
        },
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Мейн-кун + обморок = аритмия при HCM",
        },
    ],
    "мейн-кун": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Мейн-кун — высокий риск HCM",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Мейн-кун — одышка при HCM",
        },
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Мейн-кун + обморок = аритмия при HCM",
        },
    ],
    "ragdoll": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Рэгдолл — риск HCM",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Рэгдолл — одышка при HCM",
        },
    ],
    "рэгдолл": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Рэгдолл — риск HCM",
        },
    ],
    "doberman": [
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Доберман — высокий риск DCM с аритмиями",
        },
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Доберман — DCM риск",
        },
    ],
    "доберман": [
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Доберман — высокий риск DCM с аритмиями",
        },
    ],
    "boxer": [
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Боксёр — аритмогенная кардиомиопатия правого желудочка",
        },
    ],
    "боксёр": [
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Боксёр — аритмогенная кардиомиопатия",
        },
    ],

    # ── URINARY (коты предрасположены к обструкции) ───────────────
    "persian": [
        {
            "symptoms": ["urinary_straining"],
            "escalation": "HIGH",
            "reason": "Перс — предрасположен к PKD и мочекаменной болезни",
        },
        {
            "symptoms": ["blood_in_urine"],
            "escalation": "HIGH",
            "reason": "Перс — PKD риск",
        },
    ],
    "перс": [
        {
            "symptoms": ["urinary_straining"],
            "escalation": "HIGH",
            "reason": "Перс — предрасположен к PKD и МКБ",
        },
    ],
    "scottish fold": [
        {
            "symptoms": ["mild_lameness"],
            "escalation": "HIGH",
            "reason": "Шотландская вислоухая — остеохондродисплазия, хромота всегда серьёзна",
        },
        {
            "symptoms": ["pain_on_touch"],
            "escalation": "HIGH",
            "reason": "Шотландская вислоухая — хроническая боль при остеохондродисплазии",
        },
    ],
    "шотландская вислоухая": [
        {
            "symptoms": ["mild_lameness"],
            "escalation": "HIGH",
            "reason": "Шотландская вислоухая — остеохондродисплазия",
        },
    ],

    # ── КАВАЛЕР КИНГ ЧАРЛЬЗ СПАНИЕЛЬ (MVD) ──────────────────────
    "cavalier king charles spaniel": [
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Кавалер — высокий риск MVD (митральный клапан), обморок критичен",
        },
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Кавалер — MVD риск, непереносимость нагрузок",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Кавалер — одышка при MVD",
        },
    ],
    "кавалер": [
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Кавалер — MVD риск, обморок критичен",
        },
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Кавалер — MVD риск",
        },
    ],

    # ── НЕМЕЦКАЯ ОВЧАРКА (GDV) ────────────────────────────────────
    "german shepherd": [
        {
            "symptoms": ["abdominal_distension"],
            "escalation": "CRITICAL",
            "reason": "Немецкая овчарка — высокий риск GDV",
        },
        {
            "symptoms": ["bloating"],
            "escalation": "CRITICAL",
            "reason": "Немецкая овчарка + вздутие = GDV",
        },
    ],
    "немецкая овчарка": [
        {
            "symptoms": ["abdominal_distension"],
            "escalation": "CRITICAL",
            "reason": "Немецкая овчарка — высокий риск GDV",
        },
    ],

    # ── СЕНБЕРНАР / ДОГ (GDV) ────────────────────────────────────
    "saint bernard": [
        {
            "symptoms": ["abdominal_distension"],
            "escalation": "CRITICAL",
            "reason": "Сенбернар — высокий риск GDV у гигантских пород",
        },
    ],
    "сенбернар": [
        {
            "symptoms": ["abdominal_distension"],
            "escalation": "CRITICAL",
            "reason": "Сенбернар — GDV риск",
        },
    ],
    "great dane": [
        {
            "symptoms": ["abdominal_distension"],
            "escalation": "CRITICAL",
            "reason": "Дог — один из наибольших рисков GDV среди всех пород",
        },
    ],
    "дог": [
        {
            "symptoms": ["abdominal_distension"],
            "escalation": "CRITICAL",
            "reason": "Дог — очень высокий риск GDV",
        },
    ],

    # ── ЙОРКШИРСКИЙ ТЕРЬЕР (коллапс трахеи) ──────────────────────
    "yorkshire terrier": [
        {
            "symptoms": ["cough"],
            "escalation": "HIGH",
            "reason": "Йорк — риск коллапса трахеи, кашель требует осмотра",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Йорк — коллапс трахеи при одышке",
        },
        {
            "symptoms": ["collapse"],
            "escalation": "CRITICAL",
            "reason": "Йорк + коллапс = гипогликемия или трахея",
        },
    ],
    "йоркширский терьер": [
        {
            "symptoms": ["cough"],
            "escalation": "HIGH",
            "reason": "Йорк — риск коллапса трахеи",
        },
        {
            "symptoms": ["collapse"],
            "escalation": "CRITICAL",
            "reason": "Йорк + коллапс = критично",
        },
    ],
    "йорк": [
        {
            "symptoms": ["cough"],
            "escalation": "HIGH",
            "reason": "Йорк — риск коллапса трахеи",
        },
    ],

    # ── СФИНКС (HCM) ─────────────────────────────────────────────
    "sphinx": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Сфинкс — очень высокий риск HCM",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Сфинкс — одышка при HCM",
        },
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Сфинкс + обморок = аритмия при HCM",
        },
    ],
    "сфинкс": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Сфинкс — очень высокий риск HCM",
        },
        {
            "symptoms": ["syncope"],
            "escalation": "CRITICAL",
            "reason": "Сфинкс + обморок = HCM аритмия",
        },
    ],

    # ── СИБИРСКАЯ КОШКА (HCM) ────────────────────────────────────
    "siberian": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Сибирская кошка — риск HCM",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Сибирская кошка — одышка при HCM",
        },
    ],
    "сибирская": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Сибирская кошка — риск HCM",
        },
    ],

    # ── БРИТАНСКАЯ КОШКА (HCM) ───────────────────────────────────
    "british shorthair": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Британец — риск HCM",
        },
        {
            "symptoms": ["dyspnea"],
            "escalation": "HIGH",
            "reason": "Британец — одышка при HCM",
        },
    ],
    "британец": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Британец — риск HCM",
        },
    ],
    "british": [
        {
            "symptoms": ["exercise_intolerance"],
            "escalation": "HIGH",
            "reason": "Британец — риск HCM",
        },
    ],
}


# ──────────────────────────────────────────────────────────────────
# WEIGHT_RISK_RULES
# Правила на основе веса питомца
# ──────────────────────────────────────────────────────────────────

WEIGHT_RISK_RULES: List[Dict] = [
    # Крупные породы (>25 кг) — риск GDV
    {
        "weight_min_kg": 25,
        "symptoms": ["abdominal_distension"],
        "escalation": "CRITICAL",
        "reason": "Крупная порода + вздутие живота = GDV, немедленная клиника",
    },
    {
        "weight_min_kg": 25,
        "symptoms": ["bloating"],
        "escalation": "CRITICAL",
        "reason": "Крупная порода + вздутие = GDV риск",
    },
    # Маленькие собаки (<5 кг) — гипогликемия
    {
        "weight_max_kg": 5,
        "species": "dog",
        "symptoms": ["collapse"],
        "escalation": "CRITICAL",
        "reason": "Маленькая собака + коллапс = гипогликемия или сердце",
    },
    {
        "weight_max_kg": 5,
        "species": "dog",
        "symptoms": ["severe_lethargy"],
        "escalation": "HIGH",
        "reason": "Маленькая собака + сильная вялость = риск гипогликемии",
    },
]


def apply_breed_modifiers(
    detected_symptoms: List[str],
    current_escalation: str,
    breed: Optional[str] = None,
    weight_kg: Optional[float] = None,
    species: str = "dog"
) -> Tuple[str, Optional[str]]:
    """
    Применяет модификаторы породы и веса к escalation.
    Эскалация никогда не понижается.

    Аргументы:
        detected_symptoms: список нормализованных ключей симптомов
        current_escalation: текущий уровень
        breed: порода (из профиля питомца, любой регистр)
        weight_kg: вес в кг (из профиля питомца)
        species: "dog" или "cat"

    Возвращает: (новый_уровень, причина) или (текущий_уровень, None)
    """
    result = current_escalation
    reason = None

    # Шаг 1: Применяем правила породы
    if breed:
        breed_lower = breed.lower().strip()
        breed_rules = BREED_RISK_MAP.get(breed_lower, [])

        for rule in breed_rules:
            rule_symptoms = rule.get("symptoms", [])
            # Правило срабатывает если хоть один симптом из правила есть в detected
            if any(s in detected_symptoms for s in rule_symptoms):
                rule_escalation = rule.get("escalation", "LOW")
                if ESCALATION_ORDER.index(rule_escalation) > ESCALATION_ORDER.index(result):
                    result = rule_escalation
                    reason = rule.get("reason")

    # Шаг 2: Применяем правила веса
    if weight_kg is not None:
        for rule in WEIGHT_RISK_RULES:
            # Проверяем вес
            weight_min = rule.get("weight_min_kg")
            weight_max = rule.get("weight_max_kg")

            if weight_min and weight_kg < weight_min:
                continue
            if weight_max and weight_kg > weight_max:
                continue

            # Проверяем вид (если указан в правиле)
            rule_species = rule.get("species")
            if rule_species and rule_species != species:
                continue

            # Проверяем симптомы
            rule_symptoms = rule.get("symptoms", [])
            if any(s in detected_symptoms for s in rule_symptoms):
                rule_escalation = rule.get("escalation", "LOW")
                if ESCALATION_ORDER.index(rule_escalation) > ESCALATION_ORDER.index(result):
                    result = rule_escalation
                    reason = rule.get("reason")

    return result, reason
