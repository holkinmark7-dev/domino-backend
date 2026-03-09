"""Tests for ТЗ №9 FSM handler fixes — species_clarify, gender, photo_avatar, confirm_summary."""
import pytest
from routers.services.onboarding_new import (
    _handle_species_clarify,
    _handle_gender,
    _handle_photo_avatar,
    _handle_confirm_summary,
    _build_pet_card,
    OnboardingState,
)


def _flags(**kw):
    base = {"pet_name": "Рекс", "owner_name": "Марк"}
    base.update(kw)
    return base


# ── _handle_species_clarify ──────────────────────────────────────────────────

class TestSpeciesClarify:
    def test_first_call_shows_question(self):
        r = _handle_species_clarify("", {}, _flags())
        assert r["onboarding_step"] == OnboardingState.SPECIES_CLARIFY.value
        assert "кот" in r["ai_response_override"].lower() or "собака" in r["ai_response_override"].lower()
        assert r["quick_replies"] == ["Кот", "Кошка", "Собака"]

    def test_answer_kot(self):
        uf = _flags()
        r = _handle_species_clarify("Кот", {}, uf)
        assert uf["species"] == "кот"
        assert r["onboarding_step"] == OnboardingState.PASSPORT_OFFER.value

    def test_answer_koshka(self):
        uf = _flags()
        r = _handle_species_clarify("Кошка", {}, uf)
        assert uf["species"] == "кошка"

    def test_answer_sobaka(self):
        uf = _flags()
        r = _handle_species_clarify("Собака", {}, uf)
        assert uf["species"] == "собака"

    def test_answer_pes(self):
        uf = _flags()
        r = _handle_species_clarify("Пёс", {}, uf)
        assert uf["species"] == "собака"

    def test_garbage_repeats(self):
        uf = _flags()
        r = _handle_species_clarify("абракадабра", {}, uf)
        assert "species" not in uf
        assert r["onboarding_step"] == OnboardingState.SPECIES_CLARIFY.value


# ── _handle_gender ───────────────────────────────────────────────────────────

class TestGender:
    def test_first_call_shows_question(self):
        r = _handle_gender("", {}, _flags())
        assert r["onboarding_step"] == OnboardingState.GENDER.value
        assert "мальчик" in r["ai_response_override"].lower() or "девочка" in r["ai_response_override"].lower()

    def test_answer_boy(self):
        uf = _flags()
        r = _handle_gender("Мальчик", {}, uf)
        assert uf["gender"] == "самец"
        assert r["onboarding_step"] == OnboardingState.NEUTERED.value
        assert "кастрирован" in r["ai_response_override"]

    def test_answer_girl(self):
        uf = _flags()
        r = _handle_gender("Девочка", {}, uf)
        assert uf["gender"] == "самка"
        assert r["onboarding_step"] == OnboardingState.NEUTERED.value
        assert "стерилизована" in r["ai_response_override"]

    def test_answer_samets(self):
        uf = _flags()
        r = _handle_gender("самец", {}, uf)
        assert uf["gender"] == "самец"

    def test_garbage_repeats(self):
        uf = _flags()
        r = _handle_gender("абракадабра", {}, uf)
        assert "gender" not in uf
        assert r["onboarding_step"] == OnboardingState.GENDER.value


# ── _handle_photo_avatar ─────────────────────────────────────────────────────

class TestPhotoAvatar:
    def test_first_call_shows_question(self):
        r = _handle_photo_avatar("", {}, _flags())
        assert r["onboarding_step"] == OnboardingState.PHOTO_AVATAR.value
        assert "фото" in r["ai_response_override"].lower()

    def test_upload_button_opens_camera(self):
        r = _handle_photo_avatar("Загрузить фото", {}, _flags())
        assert r["input_type"] == "image"
        assert r["onboarding_step"] == OnboardingState.PHOTO_AVATAR.value

    def test_avatar_url_saves_and_advances(self):
        uf = _flags()
        r = _handle_photo_avatar("avatar_url:https://example.com/photo.jpg", {}, uf)
        assert uf["avatar_url"] == "https://example.com/photo.jpg"
        assert r["onboarding_step"] == OnboardingState.CONFIRM_SUMMARY.value

    def test_skip_advances(self):
        r = _handle_photo_avatar("Пропустить пока", {}, _flags())
        assert r["onboarding_step"] == OnboardingState.CONFIRM_SUMMARY.value


# ── _handle_confirm_summary ──────────────────────────────────────────────────

class TestConfirmSummary:
    def test_first_call_shows_card(self):
        uf = _flags(species="кот", gender="самец", neutered=True, age_years=3)
        r = _handle_confirm_summary("", {}, uf)
        assert r["onboarding_step"] == OnboardingState.CONFIRM_SUMMARY.value
        assert r["pet_card"] is not None
        assert r["pet_card"]["name"] == "Рекс"
        assert r["quick_replies"] == ["Всё верно", "Нужно исправить"]

    def test_confirm_completes(self):
        uf = _flags(species="кот", gender="самец")
        r = _handle_confirm_summary("Всё верно", {}, uf)
        assert r["onboarding_step"] == OnboardingState.COMPLETE.value
        assert "карточка" in r["ai_response_override"].lower()

    def test_fix_goes_back(self):
        uf = _flags(species="кот")
        r = _handle_confirm_summary("Нужно исправить", {}, uf)
        assert r["onboarding_step"] == OnboardingState.PET_INTRO.value

    def test_garbage_repeats_card(self):
        uf = _flags(species="кот", gender="самец")
        r = _handle_confirm_summary("привет мир", {}, uf)
        assert r["onboarding_step"] == OnboardingState.CONFIRM_SUMMARY.value
        assert r["pet_card"] is not None


# ── _build_pet_card ──────────────────────────────────────────────────────────

class TestBuildPetCard:
    def test_full_card(self):
        uf = {"pet_name": "Барсик", "species": "кот", "gender": "самец",
              "neutered": True, "age_years": 5, "breed": "Сиамский",
              "avatar_url": "https://example.com/a.jpg"}
        card = _build_pet_card(uf)
        assert card["name"] == "Барсик"
        assert card["species"] == "Кот"
        assert card["gender"] == "Самец"
        assert card["neutered"] == "Да"
        assert card["age"] == "5 лет"
        assert card["breed"] == "Сиамский"
        assert card["avatar_url"] == "https://example.com/a.jpg"

    def test_minimal_card(self):
        card = _build_pet_card({"pet_name": "X"})
        assert card["name"] == "X"
        assert card["breed"] == "не указана"
        assert card["neutered"] == "Не указано"
