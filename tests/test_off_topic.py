"""Tests for ТЗ №6 — off-topic detection and pending_question flow."""
import json
from unittest.mock import MagicMock, patch

import pytest

from routers.services.onboarding_gemini import classify_onboarding_message
from routers.services.onboarding_new import (
    _handle_pet_intro,
    _handle_breed,
    _handle_age,
    OnboardingState,
)


# ── classify_onboarding_message ──────────────────────────────────────────────

def _mock_gemini(text):
    resp = MagicMock()
    resp.text = text
    return resp


@patch("routers.services.onboarding_gemini._gemini_model")
def test_classify_answer(mock_model):
    mock_model.generate_content.return_value = _mock_gemini("answer")
    assert classify_onboarding_message("Барсик, кот, 3 года", "PET_INTRO") == "answer"


@patch("routers.services.onboarding_gemini._gemini_model")
def test_classify_question(mock_model):
    mock_model.generate_content.return_value = _mock_gemini("question")
    assert classify_onboarding_message("чем кормить британца?", "BREED") == "question"


@patch("routers.services.onboarding_gemini._gemini_model")
def test_classify_urgent(mock_model):
    mock_model.generate_content.return_value = _mock_gemini("urgent")
    assert classify_onboarding_message("он не ест два дня", "AGE") == "urgent"


@patch("routers.services.onboarding_gemini._gemini_model")
def test_classify_error_returns_answer(mock_model):
    mock_model.generate_content.side_effect = Exception("API error")
    assert classify_onboarding_message("что-то", "PET_INTRO") == "answer"


@patch("routers.services.onboarding_gemini._gemini_model")
def test_classify_garbage_returns_answer(mock_model):
    mock_model.generate_content.return_value = _mock_gemini("I think this is a question about...")
    assert classify_onboarding_message("что-то", "PET_INTRO") == "answer"


# ── _handle_pet_intro off-topic ──────────────────────────────────────────────

@patch("routers.services.onboarding_new.classify_onboarding_message")
@patch("routers.services.onboarding_new.parse_pet_info", return_value={})
def test_pet_intro_question_off_topic(mock_parse, mock_classify):
    mock_classify.return_value = "question"
    uf = {"owner_name": "Марк"}
    result = _handle_pet_intro("чем кормить кота?", {}, uf)
    assert result["onboarding_step"] == OnboardingState.PET_INTRO.value
    assert uf["pending_question"] == "чем кормить кота?"
    assert "Хорошо, продолжим" in result["quick_replies"]


@patch("routers.services.onboarding_new.classify_onboarding_message")
@patch("routers.services.onboarding_new.parse_pet_info", return_value={})
def test_pet_intro_urgent_off_topic(mock_parse, mock_classify):
    mock_classify.return_value = "urgent"
    uf = {"owner_name": "Марк"}
    result = _handle_pet_intro("он не ест два дня", {}, uf)
    assert result["onboarding_step"] == OnboardingState.PET_INTRO.value
    assert uf["pending_question"] == "он не ест два дня"
    assert "Хорошо, быстро заканчиваем" in result["quick_replies"]


@patch("routers.services.onboarding_new.classify_onboarding_message")
@patch("routers.services.onboarding_new.parse_pet_info")
@patch("routers.services.onboarding_new.apply_parsed_to_flags")
@patch("routers.services.onboarding_new.get_states_to_skip", return_value=set())
def test_pet_intro_answer_passthrough(mock_skip, mock_apply, mock_parse, mock_classify):
    mock_classify.return_value = "answer"
    mock_parse.return_value = {"pet_name": "Барсик"}
    mock_apply.side_effect = lambda parsed, uf: {**uf, **{k: v for k, v in parsed.items() if v is not None}}
    uf = {"owner_name": "Марк"}
    result = _handle_pet_intro("Барсик, кот, 3 года", {}, uf)
    # Should proceed normally — not stay on PET_INTRO
    assert result["onboarding_step"] == OnboardingState.SPECIES_CLARIFY.value


# ── _handle_breed off-topic ──────────────────────────────────────────────────

@patch("routers.services.onboarding_new.classify_onboarding_message")
def test_breed_question_off_topic(mock_classify):
    mock_classify.return_value = "question"
    uf = {"pet_name": "Барсик"}
    result = _handle_breed("когда делать прививки?", {}, uf)
    assert result["onboarding_step"] == OnboardingState.BREED.value
    assert uf["pending_question"] == "когда делать прививки?"


@patch("routers.services.onboarding_new.classify_onboarding_message")
def test_breed_answer_passthrough(mock_classify):
    """Known breed exact match should work even with classify returning answer."""
    mock_classify.return_value = "answer"
    uf = {"pet_name": "Барсик"}
    result = _handle_breed("Мейн-кун", {}, uf)
    assert uf.get("breed") == "Мейн-кун"


# ── _handle_age off-topic ────────────────────────────────────────────────────

@patch("routers.services.onboarding_new.classify_onboarding_message")
def test_age_question_off_topic(mock_classify):
    mock_classify.return_value = "question"
    uf = {"pet_name": "Барсик", "species": "кот"}
    result = _handle_age("чем кормить котёнка?", {}, uf)
    assert result["onboarding_step"] == OnboardingState.AGE.value
    assert uf["pending_question"] == "чем кормить котёнка?"


@patch("routers.services.onboarding_new.classify_onboarding_message")
def test_age_number_skips_classify(mock_classify):
    """Numbers should never trigger classify — go straight to parsing."""
    uf = {"pet_name": "Барсик", "species": "кот"}
    result = _handle_age("3", {}, uf)
    assert uf.get("age_years") == 3
    mock_classify.assert_not_called()


def test_age_iso_date_skips_classify():
    """ISO dates should never trigger classify."""
    uf = {"pet_name": "Барсик", "species": "кот"}
    # No mock needed — classify should not be called
    result = _handle_age("2022-05-15", {}, uf)
    assert uf.get("birth_date") == "2022-05-15"


# ── pending_question overwrites ──────────────────────────────────────────────

@patch("routers.services.onboarding_new.classify_onboarding_message")
def test_pending_question_overwritten_by_second_off_topic(mock_classify):
    """Second off-topic message should overwrite the first pending_question."""
    mock_classify.return_value = "question"
    uf = {"pet_name": "Барсик", "pending_question": "первый вопрос"}
    result = _handle_breed("второй вопрос про корм", {}, uf)
    assert uf["pending_question"] == "второй вопрос про корм"
