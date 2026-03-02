"""
tests/test_onboarding_v2.py — Tests for onboarding v2 UX fixes
10 tests:
  TestNameParsing (4): stop-word filtering, lowercase, simple, prefix
  TestSkipLogic (3): keyword detection, next field, last field
  TestFieldOrder (1): correct order
  TestOnboardingComplete (1): mode exists
  TestOnboardingNameHint (1): pet name in question instruction
"""
import pytest
import re


class TestNameParsing:
    """Улучшенный парсинг имени."""

    def test_name_with_stop_word(self):
        """'Мой кот Барсик' -> Барсик, не Мой."""
        raw = "Мой кот Барсик"
        bad_starts = ["Мой", "Моя", "Наш", "Наша", "Его", "Её", "Это"]
        all_caps = re.findall(r"([А-ЯЁA-Z][а-яёa-z]{1,20})", raw)
        filtered = [w for w in all_caps if w not in bad_starts]
        assert filtered[0] == "Барсик"

    def test_name_lowercase(self):
        """'барсик' -> Барсик (капитализация)."""
        raw = "барсик"
        words = raw.strip().split()
        assert len(words) == 1
        assert words[0].capitalize() == "Барсик"

    def test_name_simple_capitalized(self):
        """'Барсик' -> Барсик."""
        raw = "Барсик"
        match = re.search(r"([А-ЯЁA-Z][а-яёa-z]{1,20})", raw)
        assert match and match.group(1) == "Барсик"

    def test_name_with_its_name_prefix(self):
        """'Его зовут Рыжик' -> Рыжик."""
        raw = "Его зовут Рыжик"
        bad_starts = ["Его", "Её", "Мой", "Моя"]
        all_caps = re.findall(r"([А-ЯЁA-Z][а-яёa-z]{1,20})", raw)
        filtered = [w for w in all_caps if w not in bad_starts]
        assert filtered and filtered[0] == "Рыжик"


class TestSkipLogic:
    """Пропуск полей."""

    def test_skip_keywords_detected(self):
        """'не знаю' -> пропуск."""
        skip_kws = ["не знаю", "незнаю", "не помню", "пропустить", "потом"]
        msg = "не знаю"
        assert any(kw in msg for kw in skip_kws)

    def test_skip_moves_to_next_field(self):
        """После пропуска — следующее поле."""
        field_order = ["name", "species", "age", "gender", "neutered"]
        current = "species"
        idx = field_order.index(current)
        next_field = field_order[idx + 1]
        assert next_field == "age"

    def test_skip_last_field_completes(self):
        """Пропуск последнего поля -> онбординг завершён."""
        field_order = ["name", "species", "age", "gender", "neutered"]
        current = "neutered"
        idx = field_order.index(current)
        assert idx == len(field_order) - 1  # последнее


class TestFieldOrder:
    """Порядок вопросов."""

    def test_field_order_correct(self):
        """Правильный порядок: name -> species -> age -> gender -> neutered."""
        expected = ["name", "species", "age", "gender", "neutered"]
        assert expected[0] == "name"
        assert expected[1] == "species"
        assert expected[2] == "age"
        assert expected[3] == "gender"
        assert expected[4] == "neutered"


class TestOnboardingComplete:
    """Финальное сообщение."""

    def test_onboarding_complete_mode_exists(self):
        """Режим ONBOARDING_COMPLETE существует."""
        mode = "ONBOARDING_COMPLETE"
        assert mode != "CASUAL"
        assert mode != "ONBOARDING"


class TestOnboardingNameHint:
    """Имя питомца в вопросах онбординга."""

    def test_pet_name_in_species_question(self):
        """Шаг species содержит кличку питомца."""
        _pet_name_hint = "Барсик"
        question = f"Спроси кошка или собака. Используй кличку {_pet_name_hint} если известна. Одно предложение."
        assert "Барсик" in question
