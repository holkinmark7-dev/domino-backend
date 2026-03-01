SYMPTOM_REGISTRY = {
    "vomiting",
    "regurgitation",
    "diarrhea",
    "constipation",
    "loss_of_appetite",
    "lethargy",
    "weakness",
    "fever",
    "abdominal_pain",
    # GI — blood types
    "melena",
    "coffee_ground_vomit",
    # GI — anorexia
    "anorexia",
    # RESPIRATORY
    "cough",
    "sneezing",
    "difficulty_breathing",
    # INGESTION
    "foreign_body_ingestion",
    "bone_stuck",
    "choking",
    # TOXIC
    "poisoning",
    "xylitol_toxicity",
    "antifreeze",
    "rodenticide",
    # URINARY
    "urinary_obstruction",
    # NEURO
    "seizure",
    # OCULAR
    "eye_discharge",
    # TRAUMA
    "injury",
}


def normalize_symptom(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if value in SYMPTOM_REGISTRY:
        return value
    return None
