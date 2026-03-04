import pytest
from unittest.mock import patch
from main import app
from dependencies.auth import get_current_user
from dependencies.limiter import limiter

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"


async def mock_get_current_user():
    return {"id": TEST_USER_ID, "email": "test@test.com"}


def _noop_verify(*args, **kwargs):
    return None


@pytest.fixture(autouse=True)
def override_auth():
    limiter.enabled = False
    app.dependency_overrides[get_current_user] = mock_get_current_user
    with (
        patch("routers.pets.verify_pet_owner", _noop_verify),
        patch("routers.timeline.verify_pet_owner", _noop_verify),
        patch("routers.chat_history.verify_pet_owner", _noop_verify),
        patch("routers.vet_report.verify_pet_owner", _noop_verify),
    ):
        yield
    app.dependency_overrides.clear()
