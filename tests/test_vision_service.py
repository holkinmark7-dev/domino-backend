# tests/test_vision_service.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_call_vision_uses_gpt4o():
    """Verify _call_vision uses GPT-4o via OpenAI client."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"breed": "Labrador"}'

    with patch("routers.services.vision_service._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        from routers.services.vision_service import _call_vision
        result = await _call_vision(
            system_prompt="Determine the dog breed.",
            image_base64="ZmFrZWltYWdl",
        )

    assert isinstance(result, dict)
    assert result["breed"] == "Labrador"
    mock_client.return_value.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
    assert "gpt-4o" in call_kwargs.get("model", "")


@pytest.mark.asyncio
async def test_call_vision_passes_image_and_system_correctly():
    """Verify multimodal message format and system prompt placement."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"result": "ok"}'

    with patch("routers.services.vision_service._get_client") as mock_client:
        mock_client.return_value.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        from routers.services.vision_service import _call_vision
        await _call_vision(
            system_prompt="Analyse.",
            image_base64="abc123",
            media_type="image/png",
        )

    call_kwargs = mock_client.return_value.chat.completions.create.call_args.kwargs
    messages = call_kwargs["messages"]

    # system message
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Analyse."

    # image in user message
    image_block = messages[1]["content"][0]
    assert image_block["type"] == "image_url"
    assert "image/png" in image_block["image_url"]["url"]
    assert "abc123" in image_block["image_url"]["url"]
