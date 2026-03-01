SYMPTOM_CLASS_MAP = {
    # GI
    "vomiting": "GI",
    "diarrhea": "GI",
    "melena": "GI",
    "coffee_ground_vomit": "GI",
    "anorexia": "GI",
    "regurgitation": "GI",
    "constipation": "GI",
    "abdominal_pain": "GI",
    "loss_of_appetite": "GI",
    # RESPIRATORY
    "cough": "RESPIRATORY",
    "sneezing": "RESPIRATORY",
    "difficulty_breathing": "RESPIRATORY",
    # INGESTION
    "foreign_body_ingestion": "INGESTION",
    "bone_stuck": "INGESTION",
    "choking": "INGESTION",
    # TOXIC
    "poisoning": "TOXIC",
    "xylitol_toxicity": "TOXIC",
    "antifreeze": "TOXIC",
    "rodenticide": "TOXIC",
    # URINARY
    "difficulty_urinating": "URINARY",
    "urinary_obstruction": "URINARY",
    # NEURO
    "seizure": "NEURO",
    # OCULAR
    "eye_discharge": "OCULAR",
    # TRAUMA
    "injury": "TRAUMA",
    # GENERAL
    "fever": "GENERAL",
    "weakness": "GENERAL",
    "lethargy": "GENERAL",
}


def get_symptom_class(symptom_key: str) -> str:
    if not symptom_key:
        return "UNKNOWN"
    return SYMPTOM_CLASS_MAP.get(symptom_key, "GENERAL")
