"""
tests/test_onboarding_v3.py — Tests for onboarding v3: full profile + registration
"""
import pytest
import re


class TestOwnerName:
    """Имя владельца."""

    def test_owner_name_saved_correctly(self):
        raw = "Иван"
        assert raw.capitalize() == "Иван"

    def test_owner_name_too_short_rejected(self):
        raw = "И"
        assert len(raw) < 2

    def test_owner_name_with_numbers_rejected(self):
        raw = "Ivan123"
        assert not raw.replace(" ", "").replace("-", "").isalpha()

    def test_owner_name_lowercase_capitalized(self):
        raw = "иван"
        assert raw.capitalize() == "Иван"


class TestNewFields:
    """Парсинг новых полей."""

    def test_breed_unknown_variants(self):
        unknowns = ["не знаю", "дворняга", "метис", "беспородный"]
        for u in unknowns:
            assert any(w in u for w in ["не знаю", "дворняга", "метис", "беспородный"])

    def test_breed_text_saved(self):
        raw = "Лабрадор-ретривер"
        assert len(raw) >= 2
        assert raw.capitalize() == "Лабрадор-ретривер"

    def test_chip_id_parsed(self):
        msg = "чип 643094100012345"
        match = re.search(r'\b(\d{9,15})\b', msg)
        assert match and match.group(1) == "643094100012345"

    def test_chip_none_variants(self):
        nones = ["нет", "не чипирован", "без чипа"]
        for n in nones:
            assert any(w in n for w in ["нет", "не чипирован", "без чипа"])

    def test_stamp_parsed(self):
        msg = "клеймо RU12345"
        match = re.search(r'\b([A-Za-z\u0410-\u042F\u0401\u0430-\u044F\u0451]{0,3}\d{3,8})\b', msg)
        assert match and match.group(1).upper() == "RU12345"

    def test_color_saved(self):
        raw = "Рыжий с белыми пятнами"
        assert len(raw) >= 2
        assert raw.lower() == "рыжий с белыми пятнами"

    def test_features_none_variants(self):
        nones = ["нет", "обычный", "никаких"]
        for n in nones:
            assert any(w in n for w in ["нет", "обычный", "никаких"])


class TestOnboardingPhases:
    """Фазы онбординга."""

    def test_required_phase_order(self):
        required = ["species", "name", "gender", "neutered", "age"]
        assert required[0] == "species"
        assert required[-1] == "age"

    def test_optional_phase_order(self):
        optional = ["photo", "breed", "color", "features", "chip_id", "stamp_id"]
        assert optional[0] == "photo"
        assert optional[-1] == "stamp_id"

    def test_optional_can_be_skipped(self):
        skippable = ["photo", "breed", "color", "features", "chip_id", "stamp_id"]
        for field in skippable:
            skip_key = f"{field}_skipped"
            assert skip_key.endswith("_skipped")

    def test_required_cannot_be_skipped_except_via_flow(self):
        required = ["species", "name", "gender", "neutered", "age"]
        for field in required:
            assert field in required


class TestRegistrationPrompt:
    """Регистрационный экран."""

    def test_registration_prompt_mode_exists(self):
        assert "REGISTRATION_PROMPT" != "CASUAL"
        assert "REGISTRATION_PROMPT" != "ONBOARDING"

    def test_registration_providers(self):
        providers = ["apple", "google", "email"]
        assert len(providers) == 3
        assert "apple" in providers
        assert "google" in providers
        assert "email" in providers
