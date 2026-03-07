import json
import logging
import os
from typing import Optional

from openai import AsyncOpenAI
from routers.services.model_router import MODELS

from schemas.vision import (
    PassportResponse, PassportFields, FieldConfidence, VaccineEntry,
    BreedResponse, BreedCandidate,
    SymptomResponse,
)

logger = logging.getLogger(__name__)
_openai_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


# ── Prompts ──────────────────────────────────────────────────────────────────

PASSPORT_OCR_PROMPT = """Ты специализированная OCR-система для ветеринарных паспортов России и СНГ.

ЗАДАЧА: Извлечь структурированные данные из фотографии ветеринарного паспорта.

ФОРМАТ ОТВЕТА: Только JSON, без пояснений, без markdown-блоков.

СТРУКТУРА JSON:
{
  "pet_name_ru": string | null,
  "pet_name_lat": string | null,
  "species": "cat" | "dog" | null,
  "breed_ru": string | null,
  "breed_lat": string | null,
  "gender": "male" | "female" | null,
  "birth_date": "YYYY-MM-DD" | null,
  "color": string | null,
  "chip_id": string | null,
  "chip_install_date": "YYYY-MM-DD" | null,
  "stamp_id": string | null,
  "vaccines": [
    {
      "name": string,
      "date": "YYYY-MM-DD" | null,
      "next_date": "YYYY-MM-DD" | null,
      "batch_number": string | null
    }
  ],
  "owner_name": string | null,
  "vet_clinic": string | null,
  "field_confidence": {
    "pet_name_ru": float,
    "pet_name_lat": float,
    "species": float,
    "breed_ru": float,
    "birth_date": float,
    "gender": float,
    "color": float,
    "chip_id": float,
    "chip_install_date": float,
    "stamp_id": float,
    "vaccines": float
  },
  "overall_confidence": float,
  "parse_error": null | "poor_image" | "not_passport" | "partial"
}

ПРАВИЛА ИЗВЛЕЧЕНИЯ:

1. НИКОГДА не придумывай данные. Если поле не читается или отсутствует — верни null.

2. ДАТЫ: Преобразуй любой формат в ISO YYYY-MM-DD.
   - "15.05.2021" → "2021-05-15"
   - "15 мая 2021" → "2021-05-15"
   - "май 2021" → null (неполная дата)
   - Будущая дата рождения → null (это ошибка распознавания)

3. ИМЕНА: Кличка питомца часто пишется заглавными буквами.
   - pet_name_ru: кириллица, первая буква заглавная
   - pet_name_lat: латиница, точно как в паспорте

4. ПОЛ:
   - Кобель / Самец / Male / М → "male"
   - Сука / Самка / Female / Ж / Ст (стерилизована) → "female"

5. ВИД:
   - Кошка / Кот / кошачий / Felis catus → "cat"
   - Собака / Пёс / Canis lupus familiaris → "dog"

6. ЧИП: Номер чипа — ровно 15 цифр. Если длина другая — верни null для chip_id.

7. КЛЕЙМО: Буквенно-цифровой код, 2-20 символов.

8. ВАКЦИНЫ: Извлекай ВСЕ записи из таблицы прививок.
   - name: полное название препарата как написано
   - next_date: "Следующая вакцинация" / "Ревакцинация" — если указана
   - Если таблица пустая — верни пустой массив []

9. CONFIDENCE (0.0 — 1.0):
   - 1.0: текст чёткий, однозначно читается
   - 0.8-0.9: небольшие сомнения, но скорее всего верно
   - 0.5-0.7: размыто, возможны ошибки — пользователь должен проверить
   - < 0.5: не читается → верни null для поля, confidence < 0.5

10. overall_confidence: среднее по всем заполненным полям.
    - Если < 0.6 → parse_error = "poor_image"
    - Если фото явно не является паспортом → parse_error = "not_passport", все поля null
    - Если часть данных получена → parse_error = "partial"

11. КРИТИЧНО: НЕ путай данные хозяина и питомца.
    owner_name — это человек (владелец), pet_name — животное."""


BREED_DETECTION_PROMPT = """Ты эксперт-кинолог и фелинолог с 20-летним опытом.

ЗАДАЧА: Определить породу, окрас и другие характеристики питомца по фотографии.

ФОРМАТ ОТВЕТА: Только JSON, без пояснений, без markdown-блоков.

СТРУКТУРА JSON:
{
  "breeds": [
    {
      "name_ru": string,
      "name_lat": string,
      "probability": float
    }
  ],
  "color": string | null,
  "age_estimate": string | null,
  "confidence": float,
  "error": null | "no_animal" | "unrecognizable" | "poor_photo"
}

ПРАВИЛА:

1. ПОРОДА:
   - Верни МАКСИМУМ 3 варианта, отсортированных по вероятности (от высокой к низкой)
   - Сумма probability должна быть <= 1.0
   - Если животное явно метис: первый вариант "Метис" с описанием типа в name_lat
     Пример: {"name_ru": "Метис", "name_lat": "Mix (Лабрадор-тип)", "probability": 0.85}
   - Если порода неопределима (слишком размытое фото, необычный ракурс):
     один вариант с probability < 0.5

2. ОКРАС: Точное описание на русском.
   Примеры: "рыжий", "чёрно-белый", "серо-полосатый (табби)", "золотистый", "трёхцветный"
   Если окрас не определяется — null.

3. ВОЗРАСТ: Указывай ТОЛЬКО если очевидно по внешним признакам (котёнок/щенок vs взрослый).
   Формат: "~3 месяца", "~1-2 года", "взрослый (4-7 лет)"
   Если не очевидно — null.

4. CONFIDENCE: Общая уверенность в определении породы (0.0-1.0).
   - < 0.4: предложи "Метис" или "Не определено"

5. ОШИБКИ:
   - "no_animal": на фото нет животного
   - "unrecognizable": животное есть, но порода не определяема
   - "poor_photo": слишком тёмное/размытое фото

6. ВСЕГДА заполняй поле color если на фото есть животное — даже при низком confidence по породе."""


SYMPTOM_VISION_PROMPT_TEMPLATE = """Ты ветеринарный ИИ-ассистент. Пользователь прислал фото, связанное со здоровьем своего питомца.

ДАННЫЕ ПИТОМЦА:
{pet_context}

ЗАДАЧА: Описать то, что видно на фото, в виде структурированного медицинского наблюдения.

ФОРМАТ ОТВЕТА: Только JSON, без пояснений, без markdown-блоков.

{{
  "description": string,
  "severity_hint": "low" | "moderate" | "high" | null,
  "error": null | "no_medical_content" | "unclear_photo"
}}

ПРАВИЛА:

1. description: Текстовое описание для клинического пайплайна.
   - Пиши от третьего лица, медицинским, но понятным языком
   - Описывай только то, что видно — не додумывай диагнозы
   - Максимум 3-4 предложения
   - Пример: "На фото видно покраснение и припухлость в области правого глаза животного. \
Заметны выделения серо-жёлтого цвета. Шерсть вокруг глаза слипшаяся."

2. severity_hint:
   - "high": кровотечение, травма, явная боль, отёк дыхательных путей, судороги
   - "moderate": покраснение, выделения, небольшая припухлость, изменение цвета кожи
   - "low": незначительные изменения, косметические дефекты
   - null: если фото не связано со здоровьем питомца

3. Если на фото НЕ питомец и НЕ что-то связанное с его здоровьем:
   description = "", error = "no_medical_content" """


# ── OpenAI Vision call ────────────────────────────────────────────────────────

async def _call_vision(
    system_prompt: str,
    image_base64: str,
    max_tokens: int = 1500,
    media_type: str = "image/jpeg",
) -> dict:
    response = await _get_client().chat.completions.create(
        model=MODELS["gpt4o"].model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_base64}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
    )
    text = response.choices[0].message.content or ""
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(text.strip())


# ── Passport OCR ─────────────────────────────────────────────────────────────

async def process_passport_ocr(image_base64: str) -> PassportResponse:
    try:
        data = await _call_vision(PASSPORT_OCR_PROMPT, image_base64, max_tokens=2000)
    except Exception as e:
        logger.error("Vision passport OCR failed: %s", e)
        return PassportResponse(
            success=False,
            fields=PassportFields(),
            field_confidence=FieldConfidence(),
            overall_confidence=0.0,
            low_confidence_fields=[],
            error="parse_error",
        )

    if data.get("parse_error") == "not_passport":
        return PassportResponse(
            success=False,
            fields=PassportFields(),
            field_confidence=FieldConfidence(),
            overall_confidence=0.0,
            low_confidence_fields=[],
            error="not_passport",
        )

    overall_confidence = data.get("overall_confidence", 0.5)

    # Build fields from GPT response
    passport_field_names = set(PassportFields.model_fields.keys())
    field_kwargs = {}
    for k, v in data.items():
        if k in passport_field_names and k != "vaccines":
            field_kwargs[k] = v
    # Parse vaccines
    field_kwargs["vaccines"] = [VaccineEntry(**v) for v in data.get("vaccines", [])]
    fields = PassportFields(**field_kwargs)

    # Confidence
    fc_raw = data.get("field_confidence", {})
    confidence_field_names = set(FieldConfidence.model_fields.keys())
    fc_kwargs = {k: v for k, v in fc_raw.items() if k in confidence_field_names and isinstance(v, (int, float))}
    field_confidence = FieldConfidence(**fc_kwargs)

    low_confidence_fields = [
        field for field, score in fc_raw.items()
        if isinstance(score, (int, float)) and score < 0.75
    ]

    if overall_confidence < 0.6:
        return PassportResponse(
            success=False,
            fields=fields,
            field_confidence=field_confidence,
            overall_confidence=overall_confidence,
            low_confidence_fields=low_confidence_fields,
            error="poor_image",
        )

    return PassportResponse(
        success=True,
        fields=fields,
        field_confidence=field_confidence,
        overall_confidence=overall_confidence,
        low_confidence_fields=low_confidence_fields,
        error="partial" if low_confidence_fields else None,
    )


# ── Save confirmed passport data ─────────────────────────────────────────────

async def save_passport_data(pet_id: str, confirmed_fields: dict) -> None:
    from routers.services.memory import update_pet_profile, save_vaccines

    field_mapping = {
        "pet_name_ru": "name",
        "species": "species",
        "breed_ru": "breed",
        "gender": "gender",
        "birth_date": "birth_date",
        "color": "color",
        "chip_id": "chip_id",
        "chip_install_date": "chip_install_date",
        "stamp_id": "stamp_id",
    }

    pet_update_fields = {}
    for passport_field, pet_field in field_mapping.items():
        if confirmed_fields.get(passport_field) is not None:
            pet_update_fields[pet_field] = confirmed_fields[passport_field]

    if pet_update_fields:
        update_pet_profile(pet_id, pet_update_fields)

    vaccines = confirmed_fields.get("vaccines", [])
    if vaccines:
        save_vaccines(pet_id, vaccines)


# ── Breed detection ──────────────────────────────────────────────────────────

async def process_breed_detection(image_base64: str) -> BreedResponse:
    try:
        data = await _call_vision(BREED_DETECTION_PROMPT, image_base64, max_tokens=800)
    except Exception as e:
        logger.error("Vision breed detection failed: %s", e)
        return BreedResponse(success=False, breeds=[], confidence=0.0, error="parse_error")

    if data.get("error"):
        return BreedResponse(
            success=False, breeds=[], confidence=0.0, error=data["error"]
        )

    breeds = [BreedCandidate(**b) for b in data.get("breeds", [])]
    breeds = sorted(breeds, key=lambda x: x.probability, reverse=True)[:3]

    return BreedResponse(
        success=True,
        breeds=breeds,
        color=data.get("color"),
        age_estimate=data.get("age_estimate"),
        confidence=data.get("confidence", 0.5),
    )


# ── Symptom vision ───────────────────────────────────────────────────────────

async def process_symptom_vision(image_base64: str, pet_context: Optional[dict] = None) -> SymptomResponse:
    if pet_context:
        ctx_str = (
            f"Вид: {pet_context.get('species', 'неизвестно')}, "
            f"Порода: {pet_context.get('breed', 'неизвестно')}, "
            f"Возраст: {pet_context.get('age', 'неизвестно')}"
        )
    else:
        ctx_str = "Данные питомца недоступны"

    prompt = SYMPTOM_VISION_PROMPT_TEMPLATE.format(pet_context=ctx_str)

    try:
        data = await _call_vision(prompt, image_base64, max_tokens=600)
    except Exception as e:
        logger.error("Vision symptom analysis failed: %s", e)
        return SymptomResponse(success=False, description="", error="parse_error")

    if data.get("error") == "no_medical_content":
        return SymptomResponse(success=False, description="", error="no_medical_content")

    return SymptomResponse(
        success=True,
        description=data.get("description", ""),
        severity_hint=data.get("severity_hint"),
    )
