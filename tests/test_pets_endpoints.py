"""
Tests for /pets endpoints (POST /pets, GET /pets/{user_id}, GET /pet/{pet_id}).

Uses conftest.py autouse fixture for auth override + verify_pet_owner no-op.
Uses httpx.AsyncClient for real HTTP-level testing through FastAPI.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch, MagicMock
from main import app

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
TEST_PET_ID = "00000000-0000-0000-0000-000000000002"


def _pet_row(overrides=None):
    base = {
        "id": TEST_PET_ID,
        "user_id": TEST_USER_ID,
        "name": "Buddy",
        "species": "dog",
        "breed": "Labrador",
        "birth_date": "2020-01-01",
    }
    if overrides:
        base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# POST /pets  — создание питомца
# ══════════════════════════════════════════════════════════════════════════════
class TestCreatePet:

    @pytest.mark.asyncio
    async def test_create_pet_success(self):
        """Валидный запрос — 200, возвращает список с созданным питомцем."""
        mock_resp = MagicMock()
        mock_resp.data = [_pet_row()]

        with patch("routers.pets.supabase") as mock_sb:
            mock_sb.table.return_value.insert.return_value.execute.return_value = mock_resp
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/pets", json={
                    "user_id": TEST_USER_ID,
                    "name": "Buddy",
                    "species": "dog",
                    "breed": "Labrador",
                    "birth_date": "2020-01-01",
                })
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert body[0]["id"] == TEST_PET_ID

    @pytest.mark.asyncio
    async def test_create_pet_missing_user_id(self):
        """Без user_id — 422 Unprocessable Entity."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/pets", json={
                "name": "Buddy",
                "species": "dog",
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_pet_db_error_returns_500(self):
        """Если Supabase упал — 500, без деталей ошибки в теле."""
        with patch("routers.pets.supabase") as mock_sb:
            mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception("db down")
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/pets", json={
                    "user_id": TEST_USER_ID,
                    "name": "Buddy",
                    "species": "dog",
                })
        assert resp.status_code == 500
        # H4: детали ошибки не должны утекать клиенту
        assert "db down" not in resp.text


# ══════════════════════════════════════════════════════════════════════════════
# GET /pets/{user_id}  — список питомцев пользователя
# ══════════════════════════════════════════════════════════════════════════════
class TestGetPetsByUser:

    @pytest.mark.asyncio
    async def test_get_pets_success(self):
        """Возвращает список питомцев для существующего пользователя."""
        mock_resp = MagicMock()
        mock_resp.data = [
            _pet_row(),
            _pet_row({"id": "00000000-0000-0000-0000-000000000003", "name": "Luna"}),
        ]

        with patch("routers.pets.supabase") as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = mock_resp
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(f"/pets/{TEST_USER_ID}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_get_pets_empty_list(self):
        """Пользователь без питомцев — 200, пустой список."""
        mock_resp = MagicMock()
        mock_resp.data = []

        with patch("routers.pets.supabase") as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = mock_resp
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(f"/pets/{TEST_USER_ID}")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_get_pets_db_error_returns_500(self):
        """Если Supabase упал — 500 без деталей."""
        with patch("routers.pets.supabase") as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.side_effect = Exception("timeout")
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(f"/pets/{TEST_USER_ID}")
        assert resp.status_code == 500
        assert "timeout" not in resp.text


# ══════════════════════════════════════════════════════════════════════════════
# GET /pet/{pet_id}  — один питомец по id
# ══════════════════════════════════════════════════════════════════════════════
class TestGetPetById:

    @pytest.mark.asyncio
    async def test_get_pet_by_id_success(self):
        """Возвращает питомца по существующему pet_id."""
        mock_resp = MagicMock()
        mock_resp.data = _pet_row()

        with patch("routers.pets.supabase") as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_resp
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(f"/pet/{TEST_PET_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == TEST_PET_ID
        assert body["name"] == "Buddy"

    @pytest.mark.asyncio
    async def test_get_pet_by_id_not_found(self):
        """Несуществующий pet_id — 404."""
        mock_resp = MagicMock()
        mock_resp.data = None

        with patch("routers.pets.supabase") as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_resp
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/pet/00000000-0000-0000-0000-000000000099")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_pet_by_id_invalid_uuid(self):
        """Невалидный pet_id (не UUID) — 400."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/pet/not-a-uuid")
        assert resp.status_code == 400
