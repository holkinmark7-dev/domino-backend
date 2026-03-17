"""Tests for AI-driven onboarding (onboarding_ai.py) — mock-only, no real API calls."""

import json
from unittest.mock import MagicMock, patch, call

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────


def _gemini_response(payload) -> MagicMock:
    """Create a mock Gemini send_message response (accepts str or dict)."""
    mock = MagicMock()
    if isinstance(payload, str):
        mock.text = payload
    else:
        mock.text = json.dumps(payload, ensure_ascii=False)
    return mock


def _make_flags(collected: dict | None = None) -> dict:
    return {"onboarding_collected": collected or {}}


# Common patch targets
_PATCH_FLAGS = "routers.onboarding_ai.get_user_flags"
_PATCH_UPDATE = "routers.onboarding_ai.update_user_flags"
_PATCH_HISTORY = "routers.onboarding_ai._load_chat_history"
_PATCH_SAVE_USER = "routers.onboarding_ai._save_user_message"
_PATCH_SAVE_AI = "routers.onboarding_ai._save_ai_message"
_PATCH_CREATE_PET = "routers.onboarding_ai._create_pet"
_PATCH_GENAI = "routers.onboarding_ai.genai"
_PATCH_OPENAI = "routers.onboarding_ai.openai"


def _oai_response(text: str) -> MagicMock:
    """Create a mock OpenAI chat completion response."""
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = text
    return mock


def _run(message_text: str, collected: dict | None = None, gemini_payload: dict | None = None,
         passport_ocr_data: dict | None = None) -> dict:
    """Run handle_onboarding_ai with mocked dependencies, return response JSON."""
    from routers.onboarding_ai import handle_onboarding_ai

    if gemini_payload is None:
        gemini_payload = {
            "text": "Как тебя зовут?",
            "quick_replies": [],
            "collected": {},
            "status": "collecting",
        }

    # Gemini mock (still used for parsing helpers like _detect_name_gender)
    mock_chat = MagicMock()
    mock_chat.send_message.return_value = _gemini_response(gemini_payload)
    mock_client = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    # OpenAI mock (used for main text generation)
    ai_text = gemini_payload if isinstance(gemini_payload, str) else gemini_payload.get("text", "")
    mock_oai_client = MagicMock()
    mock_oai_client.chat.completions.create.return_value = _oai_response(ai_text)

    with (
        patch(_PATCH_FLAGS, return_value=_make_flags(collected)),
        patch(_PATCH_UPDATE),
        patch(_PATCH_HISTORY, return_value=[]),
        patch(_PATCH_SAVE_USER, return_value="msg-id-1"),
        patch(_PATCH_SAVE_AI),
        patch(_PATCH_CREATE_PET, return_value=("pet-uuid-1", 1)),
        patch(_PATCH_GENAI) as mock_genai,
        patch(_PATCH_OPENAI) as mock_openai_mod,
    ):
        mock_genai.Client.return_value = mock_client
        mock_openai_mod.OpenAI.return_value = mock_oai_client
        resp = handle_onboarding_ai(
            user_id="user-test-1",
            message_text=message_text,
            passport_ocr_data=passport_ocr_data,
        )

    import json as _json
    return _json.loads(resp.body)


# ── Test 1: Welcome ping returns greeting ────────────────────────────────────

def test_welcome_ping_returns_greeting():
    resp = _run("", gemini_payload="Привет. Я Dominik — рад что ты здесь. Как тебя зовут?")
    assert resp["ai_response"] == "Привет. Я Dominik — рад что ты здесь. Как тебя зовут?"
    assert resp["onboarding_phase"] == "collecting"
    assert resp["pet_id"] is None


# ── Test 2: Backend generates quick_replies for goal step ────────────────────

def test_quick_replies_format():
    """After owner_name+pet_name+species filled, step=goal → 4 backend-generated QR buttons."""
    resp = _run("", collected={"owner_name": "Марк", "pet_name": "Рекс", "_species_guessed": True},
                gemini_payload="Рексу повезло. Чем могу помочь?")
    assert len(resp["quick_replies"]) == 4
    assert resp["quick_replies"][0]["label"] == "Слежу за здоровьем"
    assert "value" in resp["quick_replies"][0]
    assert "preferred" in resp["quick_replies"][0]


# ── Test 3: Collected fields merge correctly ─────────────────────────────────

def test_collected_merge():
    from unittest.mock import patch as _patch

    from routers.onboarding_ai import handle_onboarding_ai

    saved_flags = {}

    def capture_update(uid, flags):
        saved_flags.update(flags)

    mock_chat = MagicMock()
    mock_chat.send_message.return_value = _gemini_response({
        "text": "Отлично. Как зовут питомца?",
        "quick_replies": [],
        "collected": {"owner_name": "Марк"},
        "status": "collecting",
    })
    mock_client = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    with (
        _patch(_PATCH_FLAGS, return_value={}),
        _patch(_PATCH_UPDATE, side_effect=capture_update),
        _patch(_PATCH_HISTORY, return_value=[]),
        _patch(_PATCH_SAVE_USER, return_value=None),
        _patch(_PATCH_SAVE_AI),
        _patch(_PATCH_CREATE_PET, return_value=None),
        _patch(_PATCH_GENAI) as mock_genai,
    ):
        mock_genai.Client.return_value = mock_client
        handle_onboarding_ai("user-1", "Марк")

    assert saved_flags.get("onboarding_collected", {}).get("owner_name") == "Марк"


# ── Test 4: Existing collected is preserved when Gemini returns null ─────────

def test_existing_collected_preserved():
    resp = _run("Буду заполнять сам", collected={"owner_name": "Марк", "pet_name": "Рекс"}, gemini_payload={
        "text": "Какая порода?",
        "quick_replies": [],
        "collected": {},  # Gemini doesn't overwrite existing
        "status": "collecting",
    })
    assert resp["collected"]["owner_name"] == "Марк"
    assert resp["collected"]["pet_name"] == "Рекс"


# ── Test 5: Complete status creates pet ──────────────────────────────────────

def test_complete_creates_pet():
    full_collected = {
        "owner_name": "Марк",
        "pet_name": "Рекс",
        "species": "dog",
        "breed": "Лабрадор",
        "birth_date": "2020-01-15",
        "gender": "male",
        "is_neutered": "Да",
        "goal": "Слежу за здоровьем",
        "_avatar_skipped": True,
        "_passport_skipped": True,
    }
    resp = _run("Нет, не кастрирован", collected=full_collected, gemini_payload={
        "text": "Карточка Рекса готова.",
        "quick_replies": [],
        "collected": {"is_neutered": "Нет"},
        "status": "complete",
    })
    assert resp["onboarding_phase"] == "complete"
    assert resp["pet_id"] == "pet-uuid-1"


# ── Test 6: Completion auto-detected from collected fields ───────────────────

def test_completion_auto_detected():
    """If all fields filled + avatar skipped → _get_current_step returns complete."""
    full = {
        "owner_name": "Аня",
        "pet_name": "Мурка",
        "species": "cat",
        "breed": "Британская",
        "birth_date": "2021-06-01",
        "gender": "female",
        "is_neutered": "Да",
        "goal": "Прививки и плановое",
        "_avatar_skipped": True,
        "_passport_skipped": True,
    }
    resp = _run("Да", collected=full, gemini_payload={
        "text": "Мурка стерилизована.",
        "quick_replies": [],
        "collected": {},
        "status": "collecting",  # Gemini says collecting but all fields are present
    })
    assert resp["onboarding_phase"] == "complete"
    assert resp["pet_id"] == "pet-uuid-1"


# ── Test 7: Pet card returned on completion ───────────────────────────────────

def test_pet_card_on_completion():
    full = {
        "owner_name": "Саша",
        "pet_name": "Барсик",
        "species": "кот",
        "breed": "Сфинкс",
        "birth_date": "2022-03-01",
        "gender": "самец",
        "is_neutered": "Да",
        "goal": "Слежу за здоровьем",
        "_avatar_skipped": True,
        "_passport_skipped": True,
    }
    resp = _run("Да", collected=full, gemini_payload={
        "text": "Карточка готова.",
        "quick_replies": [],
        "collected": {},
        "status": "complete",
    })
    # pet_card disabled — preparing for walkthrough
    assert resp["pet_card"] is None


# ── Test 8: Passport OCR data applied to collected ────────────────────────────

def test_passport_ocr_applied():
    from unittest.mock import patch as _patch
    from routers.onboarding_ai import handle_onboarding_ai

    saved = {}

    def capture(uid, flags):
        saved.update(flags)

    mock_chat = MagicMock()
    mock_chat.send_message.return_value = _gemini_response({
        "text": "Паспорт обработан. Проверь данные.",
        "quick_replies": [],
        "collected": {},
        "status": "collecting",
    })
    mock_client = MagicMock()
    mock_client.chats.create.return_value = mock_chat

    ocr = {
        "success": True,
        "confidence": 0.9,
        "pet_name": "Рокки",
        "breed": "Хаски",
        "birth_date": "2021-05-10",
        "gender": "male",
    }

    with (
        _patch(_PATCH_FLAGS, return_value={}),
        _patch(_PATCH_UPDATE, side_effect=capture),
        _patch(_PATCH_HISTORY, return_value=[]),
        _patch(_PATCH_SAVE_USER, return_value=None),
        _patch(_PATCH_SAVE_AI),
        _patch(_PATCH_CREATE_PET, return_value=None),
        _patch(_PATCH_GENAI) as mock_genai,
    ):
        mock_genai.Client.return_value = mock_client
        handle_onboarding_ai("user-1", "", passport_ocr_data=ocr)

    c = saved.get("onboarding_collected", {})
    assert c.get("pet_name") == "Рокки"
    assert c.get("breed") == "Хаски"


# ── Test 9: Passport OCR low confidence → failed marker ──────────────────────

def test_passport_ocr_low_confidence():
    from unittest.mock import patch as _patch
    from routers.onboarding_ai import handle_onboarding_ai
    import json as _json

    mock_gemini_client = MagicMock()
    mock_gemini_client.chats.create.return_value = MagicMock()

    mock_oai_client = MagicMock()
    mock_oai_client.chat.completions.create.return_value = _oai_response(
        "Фото не получилось. Попробуй ещё раз."
    )

    ocr_bad = {"success": True, "confidence": 0.3}

    with (
        _patch(_PATCH_FLAGS, return_value={}),
        _patch(_PATCH_UPDATE),
        _patch(_PATCH_HISTORY, return_value=[]),
        _patch(_PATCH_SAVE_USER, return_value=None),
        _patch(_PATCH_SAVE_AI),
        _patch(_PATCH_CREATE_PET, return_value=None),
        _patch(_PATCH_GENAI) as mock_genai,
        _patch(_PATCH_OPENAI) as mock_openai_mod,
    ):
        mock_genai.Client.return_value = mock_gemini_client
        mock_openai_mod.OpenAI.return_value = mock_oai_client
        resp = handle_onboarding_ai("user-1", "", passport_ocr_data=ocr_bad)

    body = _json.loads(resp.body)
    assert body["onboarding_phase"] == "collecting"


# ── Test 10: Gemini API error returns fallback message ───────────────────────

def test_gemini_error_returns_fallback():
    from unittest.mock import patch as _patch
    from routers.onboarding_ai import handle_onboarding_ai
    import json as _json

    mock_gemini_client = MagicMock()

    mock_oai_client = MagicMock()
    mock_oai_client.chat.completions.create.side_effect = Exception("API unavailable")

    with (
        _patch(_PATCH_FLAGS, return_value={}),
        _patch(_PATCH_UPDATE),
        _patch(_PATCH_HISTORY, return_value=[]),
        _patch(_PATCH_SAVE_USER, return_value=None),
        _patch(_PATCH_SAVE_AI),
        _patch(_PATCH_CREATE_PET, return_value=None),
        _patch(_PATCH_GENAI) as mock_genai,
        _patch(_PATCH_OPENAI) as mock_openai_mod,
    ):
        mock_genai.Client.return_value = mock_gemini_client
        mock_openai_mod.OpenAI.return_value = mock_oai_client
        resp = handle_onboarding_ai("user-1", "привет")

    body = _json.loads(resp.body)
    # On error ai_text="" → fallback kicks in
    assert len(body["ai_response"]) > 0
    assert body["onboarding_phase"] == "collecting"


# ── Test 11: Non-JSON Gemini response treated as plain text ──────────────────

def test_non_json_gemini_response():
    """OpenAI returns plain text — should work directly."""
    from unittest.mock import patch as _patch
    from routers.onboarding_ai import handle_onboarding_ai
    import json as _json

    mock_gemini_client = MagicMock()

    mock_oai_client = MagicMock()
    mock_oai_client.chat.completions.create.return_value = _oai_response(
        "Привет! Как тебя зовут?"
    )

    with (
        _patch(_PATCH_FLAGS, return_value={}),
        _patch(_PATCH_UPDATE),
        _patch(_PATCH_HISTORY, return_value=[]),
        _patch(_PATCH_SAVE_USER, return_value=None),
        _patch(_PATCH_SAVE_AI),
        _patch(_PATCH_CREATE_PET, return_value=None),
        _patch(_PATCH_GENAI) as mock_genai,
        _patch(_PATCH_OPENAI) as mock_openai_mod,
    ):
        mock_genai.Client.return_value = mock_gemini_client
        mock_openai_mod.OpenAI.return_value = mock_oai_client
        resp = handle_onboarding_ai("user-1", "")

    body = _json.loads(resp.body)
    assert "Как тебя зовут" in body["ai_response"]
    assert body["onboarding_phase"] == "collecting"


# ── Test 12: Chat history loaded for Gemini context ──────────────────────────

def test_chat_history_used_as_context():
    """Chat history is passed to OpenAI as messages context."""
    from unittest.mock import patch as _patch
    from routers.onboarding_ai import handle_onboarding_ai

    history_rows = [
        {"role": "ai", "message": "Привет. Как тебя зовут?"},
        {"role": "user", "message": "Марк"},
        {"role": "ai", "message": "Марк — и кто же у тебя живёт?"},
    ]

    captured_messages = []

    def capture_create(**kwargs):
        captured_messages.extend(kwargs.get("messages", []))
        return _oai_response("Какая порода?")

    mock_gemini_client = MagicMock()
    mock_oai_client = MagicMock()
    mock_oai_client.chat.completions.create.side_effect = capture_create

    with (
        _patch(_PATCH_FLAGS, return_value={}),
        _patch(_PATCH_UPDATE),
        _patch(_PATCH_HISTORY, return_value=history_rows),
        _patch(_PATCH_SAVE_USER, return_value=None),
        _patch(_PATCH_SAVE_AI),
        _patch(_PATCH_CREATE_PET, return_value=None),
        _patch(_PATCH_GENAI) as mock_genai,
        _patch(_PATCH_OPENAI) as mock_openai_mod,
    ):
        mock_genai.Client.return_value = mock_gemini_client
        mock_openai_mod.OpenAI.return_value = mock_oai_client
        handle_onboarding_ai("user-1", "Рекс")

    # AI-only parsing may call OpenAI for validation first,
    # then the main chat call adds system + history + user.
    # Find the system message (start of main chat call).
    system_idx = None
    for i, m in enumerate(captured_messages):
        if m["role"] == "system":
            system_idx = i
            break
    assert system_idx is not None, f"No system message found in {[m['role'] for m in captured_messages]}"
    assert captured_messages[system_idx]["role"] == "system"
    assert captured_messages[system_idx + 1]["role"] == "assistant"  # ai → assistant
    assert captured_messages[system_idx + 2]["role"] == "user"
