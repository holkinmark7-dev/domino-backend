"""Tests for ТЗ №7 — passport offer/OCR handlers + apply_passport_to_flags."""
import pytest
from routers.services.onboarding_new import (
    _handle_passport_offer,
    _handle_passport_ocr,
    _apply_passport_to_flags,
    OnboardingState,
)


def _uf():
    return {"pet_name": "Барсик", "owner_name": "Марк"}


# ── _handle_passport_offer ───────────────────────────────────────────────────

def test_passport_offer_first_call():
    result = _handle_passport_offer("", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.PASSPORT_OFFER.value
    assert "паспорт" in result["ai_response_override"].lower()
    assert "Да, сфотографирую" in result["quick_replies"]


def test_passport_offer_yes():
    result = _handle_passport_offer("Да, сфотографирую", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.PASSPORT_OCR.value
    assert result["input_type"] == "image"


def test_passport_offer_yes_short():
    result = _handle_passport_offer("да", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.PASSPORT_OCR.value


def test_passport_offer_no():
    result = _handle_passport_offer("Нет, расскажу сам", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.BREED.value
    assert result["auto_follow"] is True


def test_passport_offer_dont_know():
    result = _handle_passport_offer("Не знаю где он", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.BREED.value
    assert result["auto_follow"] is True


# ── _handle_passport_ocr ─────────────────────────────────────────────────────

def test_passport_ocr_first_call():
    result = _handle_passport_ocr("", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.PASSPORT_OCR.value
    assert result["input_type"] == "image"


def test_passport_ocr_tell_myself():
    result = _handle_passport_ocr("Расскажу сам", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.BREED.value
    assert result["auto_follow"] is True


def test_passport_ocr_retry():
    result = _handle_passport_ocr("Попробую ещё раз", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.PASSPORT_OCR.value
    assert result["input_type"] == "image"


def test_passport_ocr_unknown_input_falls_through():
    """Unknown text during OCR → fall through to BREED."""
    result = _handle_passport_ocr("какой-то текст", {}, _uf())
    assert result["onboarding_step"] == OnboardingState.BREED.value


# ── _apply_passport_to_flags ─────────────────────────────────────────────────

def test_apply_passport_basic():
    uf = {"owner_name": "Марк"}  # no pet_name — so OCR can fill it
    ocr_data = {
        "fields": {
            "pet_name_ru": "Мурка",
            "species": "cat",
            "breed_ru": "Британская короткошёрстная",
            "gender": "female",
            "birth_date": "2020-05-15",
            "color": "голубой",
        }
    }
    _apply_passport_to_flags(ocr_data, uf)
    assert uf["pet_name"] == "Мурка"
    assert uf["species"] == "кот"  # cat → кот
    assert uf["breed"] == "Британская короткошёрстная"
    assert uf["gender"] == "самка"  # female → самка
    assert uf["birth_date"] == "2020-05-15"
    assert uf["color"] == "голубой"
    assert uf.get("age_years") is not None


def test_apply_passport_no_overwrite():
    """Already-filled fields should not be overwritten."""
    uf = _uf()
    uf["species"] = "собака"
    ocr_data = {"fields": {"species": "cat", "color": "рыжий"}}
    _apply_passport_to_flags(ocr_data, uf)
    assert uf["species"] == "собака"  # kept
    assert uf["color"] == "рыжий"  # new field applied


def test_apply_passport_dog_gender():
    uf = _uf()
    ocr_data = {"fields": {"species": "dog", "gender": "male"}}
    _apply_passport_to_flags(ocr_data, uf)
    assert uf["species"] == "собака"
    assert uf["gender"] == "самец"


def test_apply_passport_updates_skip():
    """Filled fields should update onboarding_skip."""
    uf = _uf()
    uf["onboarding_skip"] = []
    ocr_data = {"fields": {"species": "cat", "breed_ru": "Сиамская", "birth_date": "2021-01-01"}}
    _apply_passport_to_flags(ocr_data, uf)
    skip = uf["onboarding_skip"]
    assert "SPECIES_CLARIFY" in skip
    assert "BREED" in skip
    assert "AGE" in skip


def test_apply_passport_flat_format():
    """OCR data can also come as flat dict (without 'fields' wrapper)."""
    uf = {"owner_name": "Марк"}  # no pet_name
    ocr_data = {"pet_name_ru": "Тузик", "species": "dog"}
    _apply_passport_to_flags(ocr_data, uf)
    assert uf["pet_name"] == "Тузик"
    assert uf["species"] == "собака"
