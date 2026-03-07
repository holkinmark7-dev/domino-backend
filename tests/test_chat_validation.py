"""
Tests for chat message validation (L3).
Empty messages are allowed (onboarding WELCOME). Missing message → 422.
pet_id is optional (null for onboarding).
"""
import pytest
from pydantic import ValidationError
from schemas.chat import ChatMessage

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
TEST_PET_ID = "00000000-0000-0000-0000-000000000002"


class TestChatMessageValidation:

    def test_empty_message_allowed(self):
        """Пустое сообщение — допустимо (onboarding WELCOME)."""
        msg = ChatMessage(user_id=TEST_USER_ID, pet_id=TEST_PET_ID, message="")
        assert msg.message == ""

    def test_whitespace_message_allowed(self):
        """Сообщение из пробелов — допустимо (обработается как пустое в handler)."""
        msg = ChatMessage(user_id=TEST_USER_ID, pet_id=TEST_PET_ID, message="   ")
        assert msg.message == "   "

    def test_missing_message_rejected(self):
        """Без поля message — ValidationError."""
        with pytest.raises(ValidationError):
            ChatMessage(user_id=TEST_USER_ID, pet_id=TEST_PET_ID)

    def test_pet_id_none_allowed(self):
        """pet_id=None — допустимо (onboarding)."""
        msg = ChatMessage(user_id=TEST_USER_ID, pet_id=None, message="привет")
        assert msg.pet_id is None

    def test_invalid_pet_id_rejected(self):
        """Невалидный pet_id — ValidationError."""
        with pytest.raises(ValidationError):
            ChatMessage(user_id=TEST_USER_ID, pet_id="not-a-uuid", message="test")
