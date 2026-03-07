"""Tests for onboarding Gemini parser — mock-only, no real API calls."""

import json
from unittest.mock import MagicMock, patch

import pytest

from routers.services.onboarding_gemini import (
    apply_parsed_to_flags,
    get_states_to_skip,
    parse_pet_info,
)


def _mock_gemini_response(result_dict: dict) -> MagicMock:
    """Create a mock Gemini response returning JSON."""
    resp = MagicMock()
    resp.text = json.dumps(result_dict, ensure_ascii=False)
    return resp


# ── Scenario 1: full text ────────────────────────────────────────────────────

@patch("routers.services.onboarding_gemini._gemini_model")
def test_parse_full_text(mock_model):
    expected = {
        "owner_name": None,
        "pet_name": "Барсик",
        "species": "кот",
        "gender": "самец",
        "birth_date": None,
        "age_years": 4,
        "age_approximate": False,
        "breed": "британская короткошёрстная",
        "color": "рыжий",
        "neutered": True,
    }
    mock_model.generate_content.return_value = _mock_gemini_response(expected)

    result = parse_pet_info("Барсик — рыжий британец, кастрированный кот, ему 4 года")

    assert result["pet_name"] == "Барсик"
    assert result["species"] == "кот"
    assert result["gender"] == "самец"
    assert result["neutered"] is True
    assert result["age_years"] == 4


# ── Scenario 2: name and species only ────────────────────────────────────────

@patch("routers.services.onboarding_gemini._gemini_model")
def test_parse_name_and_species(mock_model):
    expected = {
        "owner_name": None,
        "pet_name": "Мурка",
        "species": "кошка",
        "gender": None,
        "birth_date": None,
        "age_years": None,
        "age_approximate": None,
        "breed": None,
        "color": None,
        "neutered": None,
    }
    mock_model.generate_content.return_value = _mock_gemini_response(expected)

    result = parse_pet_info("Мурка, кошка")

    assert result["pet_name"] == "Мурка"
    assert result["species"] == "кошка"
    assert result["gender"] is None
    assert result["breed"] is None


# ── Scenario 3: approximate age ──────────────────────────────────────────────

@patch("routers.services.onboarding_gemini._gemini_model")
def test_parse_approximate_age(mock_model):
    expected = {
        "owner_name": None,
        "pet_name": "Пушок",
        "species": "собака",
        "gender": None,
        "birth_date": None,
        "age_years": 3,
        "age_approximate": True,
        "breed": None,
        "color": None,
        "neutered": None,
    }
    mock_model.generate_content.return_value = _mock_gemini_response(expected)

    result = parse_pet_info("собакен зовут Пушок, ему где-то года три")

    assert result["pet_name"] == "Пушок"
    assert result["species"] == "собака"
    assert result["age_years"] == 3
    assert result["age_approximate"] is True


# ── Scenario 4: birth date ───────────────────────────────────────────────────

@patch("routers.services.onboarding_gemini._gemini_model")
def test_parse_birth_date(mock_model):
    expected = {
        "owner_name": None,
        "pet_name": "Рекс",
        "species": "собака",
        "gender": None,
        "birth_date": "2021-03-15",
        "age_years": None,
        "age_approximate": None,
        "breed": "немецкая овчарка",
        "color": None,
        "neutered": None,
    }
    mock_model.generate_content.return_value = _mock_gemini_response(expected)

    result = parse_pet_info("Рекс, немецкая овчарка, родился 15 марта 2021")

    assert result["pet_name"] == "Рекс"
    assert result["breed"] == "немецкая овчарка"
    assert result["birth_date"] == "2021-03-15"
    assert result["age_years"] is None


# ── Scenario 5: empty/irrelevant text ────────────────────────────────────────

@patch("routers.services.onboarding_gemini._gemini_model")
def test_parse_empty_text(mock_model):
    expected = {
        "owner_name": None,
        "pet_name": None,
        "species": None,
        "gender": None,
        "birth_date": None,
        "age_years": None,
        "age_approximate": None,
        "breed": None,
        "color": None,
        "neutered": None,
    }
    mock_model.generate_content.return_value = _mock_gemini_response(expected)

    result = parse_pet_info("привет")

    assert result["pet_name"] is None
    assert result["species"] is None


# ── get_states_to_skip ────────────────────────────────────────────────────────

def test_get_states_to_skip_full():
    from routers.services.onboarding_new import OnboardingState

    parsed = {
        "species": "кот",
        "breed": "британская",
        "age_years": 4,
        "gender": "самец",
        "neutered": True,
    }
    skip = get_states_to_skip(parsed, {})

    assert OnboardingState.SPECIES_CLARIFY in skip
    assert OnboardingState.BREED in skip
    assert OnboardingState.AGE in skip
    assert OnboardingState.GENDER in skip
    assert OnboardingState.NEUTERED in skip


def test_get_states_to_skip_partial():
    from routers.services.onboarding_new import OnboardingState

    parsed = {"species": "собака", "pet_name": "Рекс"}
    skip = get_states_to_skip(parsed, {})

    assert OnboardingState.SPECIES_CLARIFY in skip
    assert OnboardingState.BREED not in skip
    assert OnboardingState.AGE not in skip


# ── apply_parsed_to_flags ────────────────────────────────────────────────────

def test_apply_parsed_no_overwrite():
    user_flags = {"owner_name": "Марк"}
    parsed = {"owner_name": "Иван", "pet_name": "Барсик"}

    result = apply_parsed_to_flags(parsed, user_flags)

    assert result["owner_name"] == "Марк"  # not overwritten
    assert result["pet_name"] == "Барсик"


def test_apply_parsed_empty():
    user_flags = {}
    parsed = {"pet_name": None, "species": None}

    result = apply_parsed_to_flags(parsed, user_flags)

    assert "pet_name" not in result
    assert "species" not in result
