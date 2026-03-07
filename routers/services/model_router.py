# routers/services/model_router.py
# Единственный модуль, который знает о провайдерах и моделях.
# Всё остальное — не знает.

from dataclasses import dataclass
from typing import Literal

Provider = Literal["openai", "anthropic", "google"]

# Уровни эскалации из risk_engine (порядок важен)
URGENT_LEVELS = {"HIGH", "CRITICAL"}


@dataclass
class ModelConfig:
    provider: Provider
    model: str
    api_key_env: str  # имя переменной окружения с ключом


# Конфигурации моделей
MODELS = {
    "gemini_flash": ModelConfig(
        provider="google",
        model="gemini-2.5-flash",
        api_key_env="GEMINI_API_KEY",
    ),
    "haiku": ModelConfig(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        api_key_env="ANTHROPIC_API_KEY",
    ),
    "sonnet": ModelConfig(
        provider="anthropic",
        model="claude-sonnet-4-6",
        api_key_env="ANTHROPIC_API_KEY",
    ),
    "gpt4o": ModelConfig(
        provider="openai",
        model="gpt-4o",
        api_key_env="OPENAI_API_KEY",
    ),
    "gpt4o_mini": ModelConfig(
        provider="openai",
        model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
    ),
}


def get_model_for_response(
    mode: str,
    escalation_level: str | None = None,
    has_image: bool = False,
) -> ModelConfig:
    """
    Выбирает модель для generate_ai_response().

    Args:
        mode: значение req.message_mode —
              CASUAL / PROFILE / CLINICAL / ONBOARDING /
              ONBOARDING_COMPLETE / ONBOARDING_OBSERVER / REGISTRATION_PROMPT
        escalation_level: строка из req.clinical_decision["escalation"] (может быть None)
                          реальные значения: LOW / MODERATE / HIGH / CRITICAL
        has_image: True если в запросе есть изображение

    Returns:
        ModelConfig с провайдером, моделью и именем env-переменной
    """
    # Изображение — всегда GPT-4o, независимо от режима
    if has_image:
        return MODELS["gpt4o"]

    # Gemini Flash — всё что не требует медицинского reasoning
    if mode in {"CASUAL", "PROFILE", "ONBOARDING", "REGISTRATION_PROMPT"}:
        return MODELS["gemini_flash"]

    # CLINICAL — зависит от уровня риска
    if mode == "CLINICAL":
        if escalation_level and escalation_level.upper() in URGENT_LEVELS:
            return MODELS["sonnet"]
        return MODELS["haiku"]

    # Fallback — любой неизвестный режим → Haiku
    return MODELS["haiku"]


def get_model_for_extraction() -> ModelConfig:
    """
    Выбирает модель для extract_event_data().
    Всегда GPT-4o-mini — структурная задача, не диалог.
    """
    return MODELS["gpt4o_mini"]
