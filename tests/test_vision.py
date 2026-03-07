"""Tests for vision service (passport OCR, breed detection, symptom analysis)."""
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from schemas.vision import (
    PassportResponse, PassportFields, FieldConfidence,
    BreedResponse, BreedCandidate,
    SymptomResponse,
)
from routers.services.vision_service import (
    process_passport_ocr,
    process_breed_detection,
    process_symptom_vision,
    save_passport_data,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_openai_response(content_dict: dict):
    """Create a mock OpenAI chat.completions.create response."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(content_dict)
    return mock_response


GOOD_PASSPORT_DATA = {
    "pet_name_ru": "Барсик",
    "pet_name_lat": "Barsik",
    "species": "cat",
    "breed_ru": "Британская короткошёрстная",
    "breed_lat": "British Shorthair",
    "gender": "male",
    "birth_date": "2020-03-15",
    "color": "серо-голубой",
    "chip_id": "643094100123456",
    "chip_install_date": "2020-06-01",
    "stamp_id": "ABC123",
    "vaccines": [
        {"name": "Нобивак Tricat Trio", "date": "2020-09-01", "next_date": "2021-09-01", "batch_number": "A1234"}
    ],
    "owner_name": "Иванов А.А.",
    "vet_clinic": "ВетКлиника Плюс",
    "field_confidence": {
        "pet_name_ru": 0.95,
        "pet_name_lat": 0.90,
        "species": 1.0,
        "breed_ru": 0.85,
        "birth_date": 0.92,
        "gender": 0.88,
        "color": 0.80,
        "chip_id": 0.95,
        "chip_install_date": 0.70,
        "stamp_id": 0.60,
        "vaccines": 0.85,
    },
    "overall_confidence": 0.86,
    "parse_error": None,
}


# ── 1. Passport OCR — good response ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_passport_ocr_mock():
    """Mock OpenAI response → verify field mapping in PassportResponse."""
    mock_resp = _mock_openai_response(GOOD_PASSPORT_DATA)

    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        result = await process_passport_ocr("fake_base64")

    assert isinstance(result, PassportResponse)
    assert result.success is True
    assert result.fields.pet_name_ru == "Барсик"
    assert result.fields.species == "cat"
    assert result.fields.gender == "male"
    assert result.fields.birth_date == "2020-03-15"
    assert result.fields.chip_id == "643094100123456"
    assert len(result.fields.vaccines) == 1
    assert result.fields.vaccines[0].name == "Нобивак Tricat Trio"
    assert result.overall_confidence == 0.86
    assert result.error is None or result.error == "partial"


# ── 2. Passport — poor image ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_passport_poor_image():
    """Mock response with overall_confidence 0.4 → error='poor_image'."""
    data = {**GOOD_PASSPORT_DATA, "overall_confidence": 0.4}
    mock_resp = _mock_openai_response(data)

    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        result = await process_passport_ocr("fake_base64")

    assert result.success is False
    assert result.error == "poor_image"
    assert result.overall_confidence == 0.4


# ── 3. Passport — not a passport ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_passport_not_passport():
    """Mock response with parse_error='not_passport' → correct error response."""
    data = {"parse_error": "not_passport", "overall_confidence": 0.0}
    mock_resp = _mock_openai_response(data)

    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        result = await process_passport_ocr("fake_base64")

    assert result.success is False
    assert result.error == "not_passport"
    assert result.fields.pet_name_ru is None


# ── 4. Breed detection — good response ──────────────────────────────────────

@pytest.mark.asyncio
async def test_breed_detection_mock():
    """Mock breed response → verify sorting by probability."""
    data = {
        "breeds": [
            {"name_ru": "Лабрадор", "name_lat": "Labrador Retriever", "probability": 0.6},
            {"name_ru": "Золотистый ретривер", "name_lat": "Golden Retriever", "probability": 0.8},
            {"name_ru": "Метис", "name_lat": "Mix", "probability": 0.1},
        ],
        "color": "золотистый",
        "age_estimate": "~2 года",
        "confidence": 0.75,
        "error": None,
    }
    mock_resp = _mock_openai_response(data)

    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        result = await process_breed_detection("fake_base64")

    assert result.success is True
    assert len(result.breeds) == 3
    # Sorted by probability descending
    assert result.breeds[0].name_ru == "Золотистый ретривер"
    assert result.breeds[0].probability == 0.8
    assert result.breeds[1].name_ru == "Лабрадор"
    assert result.color == "золотистый"
    assert result.confidence == 0.75


# ── 5. Breed — no animal ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_breed_no_animal():
    """Mock response with error='no_animal' → success=False."""
    data = {"breeds": [], "confidence": 0.0, "error": "no_animal"}
    mock_resp = _mock_openai_response(data)

    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        result = await process_breed_detection("fake_base64")

    assert result.success is False
    assert result.error == "no_animal"
    assert result.breeds == []


# ── 6. Symptom vision — good response ───────────────────────────────────────

@pytest.mark.asyncio
async def test_symptom_vision_mock():
    """Mock symptom response → verify description field."""
    data = {
        "description": "На фото видно покраснение в области правого глаза.",
        "severity_hint": "moderate",
        "error": None,
    }
    mock_resp = _mock_openai_response(data)

    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        result = await process_symptom_vision("fake_base64", pet_context={"species": "cat"})

    assert result.success is True
    assert "покраснение" in result.description
    assert result.severity_hint == "moderate"


# ── 7. Save vaccines — upsert ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_vaccines_upsert():
    """Mock Supabase → verify vaccines saved without duplicates."""
    vaccines = [
        {"name": "Нобивак", "date": "2020-09-01", "next_date": "2021-09-01", "batch_number": "A1"},
        {"name": "Рабизин", "date": "2021-01-15", "next_date": None, "batch_number": None},
    ]

    with patch("routers.services.memory.supabase") as mock_sb:
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.upsert.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        from routers.services.memory import save_vaccines
        save_vaccines("pet-123", vaccines)

        assert mock_sb.table.call_count == 2
        mock_sb.table.assert_any_call("pet_vaccines")

        # Verify both vaccines were upserted
        calls = mock_table.upsert.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0]["name"] == "Нобивак"
        assert calls[1][0][0]["name"] == "Рабизин"
        assert calls[0][0][0]["source"] == "passport_ocr"


# ── 8. Passport OCR — API exception ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_passport_ocr_api_error():
    """OpenAI API raises exception → graceful error response."""
    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API timeout"))
        result = await process_passport_ocr("fake_base64")

    assert result.success is False
    assert result.error == "parse_error"


# ── 9. Low confidence fields detection ───────────────────────────────────────

@pytest.mark.asyncio
async def test_passport_low_confidence_fields():
    """Fields with confidence < 0.75 appear in low_confidence_fields."""
    data = {
        **GOOD_PASSPORT_DATA,
        "field_confidence": {
            "pet_name_ru": 0.95,
            "pet_name_lat": 0.50,  # low
            "species": 1.0,
            "breed_ru": 0.60,     # low
            "birth_date": 0.92,
            "gender": 0.88,
            "color": 0.80,
            "chip_id": 0.95,
            "chip_install_date": 0.70,  # low
            "stamp_id": 0.40,          # low
            "vaccines": 0.85,
        },
        "overall_confidence": 0.78,
    }
    mock_resp = _mock_openai_response(data)

    with patch("routers.services.vision_service._get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        result = await process_passport_ocr("fake_base64")

    assert result.success is True
    assert "pet_name_lat" in result.low_confidence_fields
    assert "breed_ru" in result.low_confidence_fields
    assert "chip_install_date" in result.low_confidence_fields
    assert "stamp_id" in result.low_confidence_fields
    assert "pet_name_ru" not in result.low_confidence_fields
    assert result.error == "partial"
