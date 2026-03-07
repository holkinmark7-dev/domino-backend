"""
Onboarding Gemini parser — извлекает данные о питомце из свободного текста.
Изолированный модуль: только парсинг, без FSM и без записей в БД.
"""

import json
import os

import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
_gemini_model = genai.GenerativeModel("gemini-1.5-flash")


GEMINI_PARSE_PROMPT = """
Ты парсер данных о питомце. Извлеки из текста пользователя следующие поля.

ПОЛЯ:
- owner_name: имя владельца (строка, только имя без фамилии)
- pet_name: кличка питомца (строка)
- species: вид — только "кот", "кошка" или "собака" (строка)
- gender: пол — только "самец" или "самка" (строка)
- birth_date: дата рождения в формате YYYY-MM-DD (строка или null)
- age_years: возраст в годах (число или null) — только если дата не известна
- age_approximate: true если возраст примерный (например "около трёх лет")
- breed: порода на русском (строка или null)
- color: окрас на русском (строка или null)
- neutered: кастрирован/стерилизован — true, false, или null если не упомянуто

ПРАВИЛА:
- Возвращай ТОЛЬКО JSON, без пояснений и без markdown
- Если поле не упомянуто — верни null
- Для gender: кобель/мальчик/самец → "самец", сука/девочка/самка → "самка"
- Для species: кот/котик/кошак → "кот", кошка/кошечка → "кошка", собака/пёс/собакен/пёсик → "собака"
- Для neutered: кастрирован/кастрат → true, стерилизована → true, не кастрирован → false
- birth_date приоритетнее age_years — если есть дата, age_years = null
- Если возраст примерный ("около", "примерно", "где-то", "лет") — age_approximate = true

ПРИМЕР ВХОДА: "Барсик — рыжий британец, кастрированный кот, ему 4 года"
ПРИМЕР ВЫХОДА:
{
  "owner_name": null,
  "pet_name": "Барсик",
  "species": "кот",
  "gender": "самец",
  "birth_date": null,
  "age_years": 4,
  "age_approximate": false,
  "breed": "британская короткошёрстная",
  "color": "рыжий",
  "neutered": true
}
"""


def parse_pet_info(text: str) -> dict:
    """
    Парсит свободный текст пользователя через Gemini.
    Возвращает словарь с извлечёнными полями.
    Все незаполненные поля = None.
    При ошибке возвращает пустой словарь.
    """
    try:
        response = _gemini_model.generate_content(
            GEMINI_PARSE_PROMPT + f"\n\nТЕКСТ ПОЛЬЗОВАТЕЛЯ: {text}"
        )
        raw = response.text.strip()
        # Убрать возможные markdown-обёртки
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return {}


def get_states_to_skip(parsed: dict, user_flags: dict) -> set:
    """
    На основе распарсенных данных возвращает множество состояний
    которые можно пропустить — поле уже известно.
    """
    from .onboarding_new import OnboardingState
    skip = set()

    if parsed.get("species"):
        skip.add(OnboardingState.SPECIES_CLARIFY)

    if parsed.get("breed"):
        skip.add(OnboardingState.BREED)

    if parsed.get("birth_date") or parsed.get("age_years") is not None:
        skip.add(OnboardingState.AGE)

    if parsed.get("gender"):
        skip.add(OnboardingState.GENDER)

    if parsed.get("neutered") is not None:
        skip.add(OnboardingState.NEUTERED)

    return skip


def apply_parsed_to_flags(parsed: dict, user_flags: dict) -> dict:
    """
    Сохраняет распарсенные поля в user_flags.
    Не перезаписывает поля которые уже заполнены.
    """
    fields = [
        "owner_name", "pet_name", "species", "gender",
        "birth_date", "age_years", "age_approximate",
        "breed", "color", "neutered",
    ]
    for field in fields:
        value = parsed.get(field)
        if value is not None and not user_flags.get(field):
            user_flags[field] = value
    return user_flags
