"""Tests for _handle_neutered — ТЗ №5 neutered bug fix."""
import pytest
from routers.services.onboarding_new import _handle_neutered, OnboardingState


def _flags(gender="самец"):
    return {"pet_name": "Барсик", "gender": gender}


# ── First call (no input) — shows question ──────────────────────────────────

def test_neutered_first_call_male():
    result = _handle_neutered("", {}, _flags("самец"))
    assert result["onboarding_step"] == OnboardingState.NEUTERED.value
    assert "кастрирован" in result["ai_response_override"]


def test_neutered_first_call_female():
    result = _handle_neutered("", {}, _flags("самка"))
    assert result["onboarding_step"] == OnboardingState.NEUTERED.value
    assert "стерилизована" in result["ai_response_override"]


# ── Answer: "Да" ─────────────────────────────────────────────────────────────

def test_neutered_yes():
    uf = _flags()
    result = _handle_neutered("Да", {}, uf)
    assert uf["neutered"] is True
    assert result["onboarding_step"] == OnboardingState.PHOTO_AVATAR.value
    assert "фото" in result["ai_response_override"].lower()  # combined photo question


# ── Answer: "Нет" ────────────────────────────────────────────────────────────

def test_neutered_no():
    uf = _flags()
    result = _handle_neutered("Нет", {}, uf)
    assert uf["neutered"] is False
    assert result["onboarding_step"] == OnboardingState.PHOTO_AVATAR.value


# ── Answer: "Не знаю" ────────────────────────────────────────────────────────

def test_neutered_unknown():
    uf = _flags()
    result = _handle_neutered("Не знаю", {}, uf)
    assert "neutered" in uf  # explicitly set
    assert uf["neutered"] is None
    assert result["onboarding_step"] == OnboardingState.PHOTO_AVATAR.value


# ── Garbage input — repeat question ──────────────────────────────────────────

def test_neutered_garbage_repeats():
    uf = _flags()
    result = _handle_neutered("абракадабра", {}, uf)
    assert "neutered" not in uf
    assert result["onboarding_step"] == OnboardingState.NEUTERED.value
    assert "кастрирован" in result["ai_response_override"]


# ── user_flags in response ───────────────────────────────────────────────────

def test_neutered_response_contains_user_flags():
    uf = _flags()
    result = _handle_neutered("Да", {}, uf)
    assert "user_flags" in result
    assert result["user_flags"]["gender"] == "самец"
