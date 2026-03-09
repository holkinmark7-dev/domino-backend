"""Tests for ТЗ №8 — breed detection via photo in _handle_breed."""
from routers.services.onboarding_new import (
    _handle_breed,
    OnboardingState,
)


def _uf():
    return {"pet_name": "Барсик", "owner_name": "Марк"}


# ── First call — quick_replies include photo option ──────────────────────────

def test_breed_first_call_has_photo_option():
    result = _handle_breed("", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.BREED.value
    assert "Сфотографирую питомца" in result["quick_replies"]
    assert "Не знаю породу" in result["quick_replies"]
    assert "Дворняга или метис" in result["quick_replies"]


# ── "Сфотографирую питомца" triggers camera ──────────────────────────────────

def test_breed_photo_trigger():
    result = _handle_breed("Сфотографирую питомца", {}, _uf())
    assert result["input_type"] == "image"
    assert result["onboarding_step"] == OnboardingState.BREED.value


def test_breed_retry_trigger():
    result = _handle_breed("Попробовать ещё раз", {}, _uf())
    assert result["input_type"] == "image"


def test_breed_po_foto_trigger():
    result = _handle_breed("По фото", {}, _uf())
    assert result["input_type"] == "image"


# ── Vision result: single breed high confidence ──────────────────────────────

def test_breed_vision_single_breed():
    uf = _uf()
    uf["_breed_vision_result"] = {
        "success": True,
        "breeds": [{"name_ru": "Лабрадор-ретривер", "name_lat": "Labrador Retriever", "probability": 0.85}],
        "color": "палевый",
        "confidence": 0.85,
    }
    result = _handle_breed("Фото обработано", {}, uf)
    assert result["onboarding_step"] == OnboardingState.BREED.value
    assert "Лабрадор-ретривер" in result["ai_response_override"]
    assert uf.get("_breed_pending") == "Лабрадор-ретривер"
    # Color should be saved
    assert uf.get("color") == "палевый"


# ── Vision result: multiple breeds ───────────────────────────────────────────

def test_breed_vision_multiple_breeds():
    uf = _uf()
    uf["_breed_vision_result"] = {
        "success": True,
        "breeds": [
            {"name_ru": "Немецкая овчарка", "name_lat": "German Shepherd", "probability": 0.5},
            {"name_ru": "Бельгийская овчарка", "name_lat": "Belgian Shepherd", "probability": 0.35},
            {"name_ru": "Восточно-европейская овчарка", "name_lat": "East European Shepherd", "probability": 0.15},
        ],
        "color": None,
        "confidence": 0.5,
    }
    result = _handle_breed("Фото обработано", {}, uf)
    qr = result["quick_replies"]
    assert "Немецкая овчарка" in qr
    assert "Бельгийская овчарка" in qr
    assert "Другая" in qr


# ── Vision error: no_animal ──────────────────────────────────────────────────

def test_breed_vision_error_no_animal():
    uf = _uf()
    uf["_breed_vision_result"] = {
        "success": False,
        "breeds": [],
        "confidence": 0.0,
        "error": "no_animal",
    }
    result = _handle_breed("Фото обработано", {}, uf)
    assert "не видно животного" in result["ai_response_override"].lower()
    assert "Попробовать ещё раз" in result["quick_replies"]


# ── Vision error: poor_photo ─────────────────────────────────────────────────

def test_breed_vision_error_poor_photo():
    uf = _uf()
    uf["_breed_vision_result"] = {
        "success": False,
        "breeds": [],
        "confidence": 0.0,
        "error": "poor_photo",
    }
    result = _handle_breed("Фото обработано", {}, uf)
    assert "темное" in result["ai_response_override"].lower() or "размытое" in result["ai_response_override"].lower()
    assert "Попробовать ещё раз" in result["quick_replies"]


# ── Vision error: generic parse_error ────────────────────────────────────────

def test_breed_vision_error_generic():
    uf = _uf()
    uf["_breed_vision_result"] = {
        "success": False,
        "breeds": [],
        "confidence": 0.0,
        "error": "parse_error",
    }
    result = _handle_breed("Фото обработано", {}, uf)
    assert "Не удалось определить" in result["ai_response_override"]
    assert "Попробовать ещё раз" in result["quick_replies"]


# ── Vision: color saved but not overwritten ──────────────────────────────────

def test_breed_vision_color_not_overwritten():
    uf = _uf()
    uf["color"] = "черный"
    uf["_breed_vision_result"] = {
        "success": True,
        "breeds": [{"name_ru": "Лабрадор-ретривер", "name_lat": "Labrador Retriever", "probability": 0.9}],
        "color": "палевый",
        "confidence": 0.9,
    }
    result = _handle_breed("Фото обработано", {}, uf)
    assert uf["color"] == "черный"  # Not overwritten


# ── Vision: empty breeds list ────────────────────────────────────────────────

def test_breed_vision_empty_breeds():
    uf = _uf()
    uf["_breed_vision_result"] = {
        "success": True,
        "breeds": [],
        "color": None,
        "confidence": 0.0,
    }
    result = _handle_breed("Фото обработано", {}, uf)
    assert "Не удалось определить" in result["ai_response_override"]
    assert "Не знаю породу" in result["quick_replies"]


# ── Vision result consumed (popped from flags) ──────────────────────────────

def test_breed_vision_result_consumed():
    uf = _uf()
    uf["_breed_vision_result"] = {
        "success": True,
        "breeds": [{"name_ru": "Пудель", "name_lat": "Poodle", "probability": 0.9}],
        "color": None,
        "confidence": 0.9,
    }
    _handle_breed("Фото обработано", {}, uf)
    assert "_breed_vision_result" not in uf
