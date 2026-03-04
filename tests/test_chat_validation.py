"""
Tests for chat message validation (L3).
Empty and whitespace-only messages must be rejected with 422.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from main import app

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
TEST_PET_ID = "00000000-0000-0000-0000-000000000002"


class TestChatMessageValidation:

    @pytest.mark.asyncio
    async def test_empty_message_rejected(self):
        """Пустое сообщение — 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/chat", json={
                "user_id": TEST_USER_ID,
                "pet_id": TEST_PET_ID,
                "message": ""
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_whitespace_only_message_rejected(self):
        """Сообщение из пробелов — 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/chat", json={
                "user_id": TEST_USER_ID,
                "pet_id": TEST_PET_ID,
                "message": "   "
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_message_rejected(self):
        """Без поля message — 422."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/chat", json={
                "user_id": TEST_USER_ID,
                "pet_id": TEST_PET_ID,
            })
        assert resp.status_code == 422
