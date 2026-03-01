# combo_matrix.py
# Опасные комбинации симптомов — override escalation
# Применяется ПОСЛЕ базового triage из symptom_registry_v2
# Python 3.9 compatible

from typing import Optional, List, Dict, Tuple

ESCALATION_ORDER = ["LOW", "MODERATE", "HIGH", "CRITICAL"]

# ВНИМАНИЕ: все ключи симптомов должны точно совпадать
# с ключами в symptom_registry_v2.py

COMBO_MATRIX: List[Dict] = [

    # ── GI КОМБО ──────────────────────────────────────────

    {
        "symptoms": ["vomiting", "abdominal_distension"],
        "escalation": "CRITICAL",
        "reason": "Подозрение GDV — жизнеугрожающее состояние",
    },
    {
        "symptoms": ["vomiting", "toy_swallowed"],
        "escalation": "CRITICAL",
        "reason": "Инородное тело + рвота = обструкция кишечника",
    },
    {
        "symptoms": ["vomiting", "plastic_swallowed"],
        "escalation": "CRITICAL",
        "reason": "Инородное тело + рвота = обструкция кишечника",
    },
    {
        "symptoms": ["vomiting", "bone_swallowed"],
        "escalation": "CRITICAL",
        "reason": "Инородное тело + рвота = обструкция кишечника",
    },
    {
        "symptoms": ["vomiting", "sock_clothing_swallowed"],
        "escalation": "CRITICAL",
        "reason": "Инородное тело + рвота = обструкция кишечника",
    },
    {
        "symptoms": ["vomiting", "lethargy"],
        "escalation": "HIGH",
        "reason": "Системное вовлечение при рвоте",
    },
    {
        "symptoms": ["diarrhea", "blood_in_stool"],
        "escalation": "HIGH",
        "reason": "Геморрагический гастроэнтерит",
    },
    {
        "symptoms": ["anorexia", "lethargy"],
        "escalation": "HIGH",
        "reason": "Системная реакция — отказ от еды + вялость",
    },
    {
        "symptoms": ["anorexia", "vomiting"],
        "escalation": "HIGH",
        "reason": "Комбинация резко ухудшает прогноз",
    },
    {
        "symptoms": ["refusing_water", "vomiting"],
        "escalation": "CRITICAL",
        "reason": "Обезвоживание + рвота = декомпенсация",
    },
    {
        "symptoms": ["diarrhea", "lethargy"],
        "escalation": "HIGH",
        "reason": "Системное вовлечение при диарее",
    },

    # ── RESP КОМБО ─────────────────────────────────────────

    {
        "symptoms": ["dyspnea", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Декомпенсированная дыхательная недостаточность",
    },
    {
        "symptoms": ["cough", "dyspnea"],
        "escalation": "HIGH",
        "reason": "Возможная сердечная или лёгочная недостаточность",
    },
    {
        "symptoms": ["respiratory_rate_high", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Тахипноэ + вялость = декомпенсация",
    },

    # ── NEURO КОМБО ────────────────────────────────────────

    {
        "symptoms": ["seizure_short", "vomiting"],
        "escalation": "CRITICAL",
        "reason": "Отравление или тяжёлая неврологическая патология",
    },
    {
        "symptoms": ["ataxia", "vomiting"],
        "escalation": "HIGH",
        "reason": "Вестибулярная патология или интоксикация",
    },
    {
        "symptoms": ["hind_limb_weakness", "incontinence"],
        "escalation": "CRITICAL",
        "reason": "Миелопатия — требует срочной неврологической помощи",
    },
    {
        "symptoms": ["disorientation", "lethargy"],
        "escalation": "HIGH",
        "reason": "ЦНС-вовлечение",
    },

    # ── CARDIAC КОМБО ──────────────────────────────────────

    {
        "symptoms": ["tachycardia_resting", "lethargy"],
        "escalation": "HIGH",
        "reason": "Гемодинамическая нестабильность",
    },
    {
        "symptoms": ["tachycardia_resting", "dyspnea"],
        "escalation": "CRITICAL",
        "reason": "Острая сердечная недостаточность",
    },
    {
        "symptoms": ["ascites_suspected", "dyspnea"],
        "escalation": "CRITICAL",
        "reason": "Правожелудочковая недостаточность с выпотом",
    },
    {
        "symptoms": ["exercise_intolerance", "dyspnea"],
        "escalation": "HIGH",
        "reason": "Сердечная недостаточность",
    },
    {
        "symptoms": ["rapid_weight_gain", "dyspnea"],
        "escalation": "HIGH",
        "reason": "Накопление жидкости при сердечной недостаточности",
    },

    # ── DERM КОМБО ─────────────────────────────────────────

    {
        "symptoms": ["facial_swelling", "vomiting"],
        "escalation": "CRITICAL",
        "reason": "Анафилаксия",
    },
    {
        "symptoms": ["hives_generalized", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Системная аллергическая реакция с декомпенсацией",
    },
    {
        "symptoms": ["severe_pruritus", "facial_swelling"],
        "escalation": "HIGH",
        "reason": "Аллергическая реакция с отёком",
    },

    # ── MUSCULO КОМБО ──────────────────────────────────────

    {
        "symptoms": ["cannot_stand", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Тяжёлое системное состояние",
    },
    {
        "symptoms": ["pain_on_touch", "lethargy"],
        "escalation": "HIGH",
        "reason": "Системное воспаление или тяжёлая травма",
    },
    {
        "symptoms": ["hind_limb_weakness", "pain_on_touch"],
        "escalation": "HIGH",
        "reason": "Неврологическая патология с болевым синдромом",
    },

    # ── TEMP КОМБО ─────────────────────────────────────────

    {
        "symptoms": ["fever_high", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Температура >= 40 + вялость = декомпенсация",
    },
    {
        "symptoms": ["fever_mild", "lethargy"],
        "escalation": "HIGH",
        "reason": "Температура + вялость = системная реакция",
    },
    {
        "symptoms": ["hypothermia", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Гипотермия + вялость = критическое системное состояние",
    },

    # ── CROSS-SYSTEM КОМБО ─────────────────────────────────

    {
        "symptoms": ["anorexia", "ocular_discharge"],
        "escalation": "HIGH",
        "reason": "Возможная чума плотоядных (дистемпер)",
        "species": "dog",
    },
    {
        "symptoms": ["vomiting", "seizure_short"],
        "escalation": "CRITICAL",
        "reason": "Отравление или метаболическая энцефалопатия",
    },
    {
        "symptoms": ["lethargy", "hypothermia"],
        "escalation": "CRITICAL",
        "reason": "Критическое системное состояние",
    },

    # ── НОВЫЕ КОМБО ПО РЕЗУЛЬТАТАМ ВЕТЕРИНАРНОЙ ПРОВЕРКИ (М8) ──

    # Судорога + рвота → CRITICAL (аспирация, интоксикация)
    {
        "symptoms": ["seizure_long", "vomiting"],
        "escalation": "CRITICAL",
        "reason": "Судорога + рвота — риск аспирационной пневмонии или интоксикации",
    },

    # Травма + вялость → CRITICAL (внутреннее кровотечение)
    {
        "symptoms": ["trauma", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Травма + вялость — возможное внутреннее кровотечение",
    },
    {
        "symptoms": ["trauma", "severe_lethargy"],
        "escalation": "CRITICAL",
        "reason": "Травма + сильная вялость — внутреннее кровотечение",
    },

    # Одышка + синюшность → CRITICAL (дыхательная недостаточность)
    {
        "symptoms": ["dyspnea", "cyanosis"],
        "escalation": "CRITICAL",
        "reason": "Одышка + синюшность = острая дыхательная недостаточность",
    },
    {
        "symptoms": ["labored_breathing", "cyanosis"],
        "escalation": "CRITICAL",
        "reason": "Затруднённое дыхание + синюшность = критическая гипоксия",
    },

    # Кашель + одышка → CRITICAL
    {
        "symptoms": ["cough", "dyspnea"],
        "escalation": "CRITICAL",
        "reason": "Кашель + одышка — острая дыхательная патология",
    },
    {
        "symptoms": ["cough", "labored_breathing"],
        "escalation": "HIGH",
        "reason": "Кашель + затруднённое дыхание — требует срочного осмотра сегодня",
    },

    # Внезапная слепота у кошки → CRITICAL (гипертония, тромбоэмболия)
    {
        "symptoms": ["sudden_blindness", "disorientation"],
        "escalation": "CRITICAL",
        "reason": "Внезапная слепота + дезориентация у кошки — гипертония или тромбоэмболия",
        "species": "cat",
    },

    # Острый живот → CRITICAL
    {
        "symptoms": ["abdominal_pain", "abdominal_distension"],
        "escalation": "CRITICAL",
        "reason": "Боль + вздутие живота — острая хирургическая патология",
    },

    # Кот-самец + мочевые симптомы → ближе к CRITICAL
    {
        "symptoms": ["urinary_straining", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Кот: задержка мочи + вялость = уремия, срочно",
        "species": "cat",
    },
    {
        "symptoms": ["frequent_urination", "lethargy"],
        "escalation": "HIGH",
        "reason": "Кот: частое мочеиспускание + вялость = обструкция под вопросом",
        "species": "cat",
    },

    # Температура 40-41 + вялость → CRITICAL (уточнение от ветеринара)
    {
        "symptoms": ["fever", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Высокая температура + вялость = тяжёлая инфекция или сепсис",
    },
    {
        "symptoms": ["fever", "severe_lethargy"],
        "escalation": "CRITICAL",
        "reason": "Лихорадка + сильная вялость = системная патология",
    },

    # Рвота + вялость (выраженная) → CRITICAL
    {
        "symptoms": ["vomiting", "severe_lethargy"],
        "escalation": "CRITICAL",
        "reason": "Рвота + сильная вялость — системное поражение",
    },

    # Диарея + мелена → CRITICAL (чёрный стул = кровотечение ЖКТ)
    {
        "symptoms": ["diarrhea", "melena"],
        "escalation": "CRITICAL",
        "reason": "Диарея + мелена = кровотечение в верхних отделах ЖКТ",
    },

    # Отказ от еды + вялость у кошки → CRITICAL
    {
        "symptoms": ["anorexia", "lethargy"],
        "escalation": "CRITICAL",
        "reason": "Кошка: отказ от еды + вялость = риск липидоза печени",
        "species": "cat",
    },
]


def apply_combo_matrix(
    detected_symptoms: List[str],
    current_escalation: str,
    species: str = "dog"
) -> Tuple[str, Optional[str]]:
    """
    Проверяет комбинации симптомов.
    Возвращает (новый_уровень, причина) или (текущий_уровень, None).
    Эскалация никогда не понижается.
    """
    result = current_escalation
    reason = None

    for combo in COMBO_MATRIX:
        # Пропускаем видо-специфичные комбо если вид не совпадает
        if "species" in combo and combo["species"] != species:
            continue
        # Проверяем наличие ВСЕХ симптомов из комбо
        if all(s in detected_symptoms for s in combo["symptoms"]):
            combo_level = combo["escalation"]
            if ESCALATION_ORDER.index(combo_level) > ESCALATION_ORDER.index(result):
                result = combo_level
                reason = combo["reason"]

    return result, reason
