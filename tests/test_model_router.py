# tests/test_model_router.py
import pytest
from routers.services.model_router import get_model_for_response, get_model_for_extraction


def test_casual_returns_gemini():
    config = get_model_for_response(mode="CASUAL")
    assert config.provider == "google"
    assert "flash" in config.model.lower()


def test_onboarding_returns_gemini():
    config = get_model_for_response(mode="ONBOARDING")
    assert config.provider == "google"
    assert "flash" in config.model.lower()


def test_profile_returns_gemini():
    config = get_model_for_response(mode="PROFILE")
    assert config.provider == "google"
    assert "flash" in config.model.lower()


def test_clinical_low_risk_returns_haiku():
    config = get_model_for_response(mode="CLINICAL", escalation_level="MODERATE")
    assert config.provider == "anthropic"
    assert "haiku" in config.model.lower()


def test_clinical_high_returns_sonnet():
    config = get_model_for_response(mode="CLINICAL", escalation_level="HIGH")
    assert config.provider == "anthropic"
    assert "sonnet" in config.model.lower()


def test_clinical_critical_returns_sonnet():
    config = get_model_for_response(mode="CLINICAL", escalation_level="CRITICAL")
    assert config.provider == "anthropic"
    assert "sonnet" in config.model.lower()


def test_has_image_always_returns_gpt4o():
    # Даже CASUAL с картинкой → GPT-4o
    config = get_model_for_response(mode="CASUAL", has_image=True)
    assert config.provider == "openai"
    assert "gpt-4o" in config.model


def test_extraction_always_gpt4o_mini():
    config = get_model_for_extraction()
    assert config.provider == "openai"
    assert "mini" in config.model


def test_unknown_mode_returns_haiku():
    # Fallback на haiku для неизвестного режима
    config = get_model_for_response(mode="SOMETHING_NEW")
    assert config.provider == "anthropic"
