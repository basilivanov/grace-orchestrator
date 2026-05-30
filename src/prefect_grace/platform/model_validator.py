"""
Model availability validation.
"""
from typing import List, Dict

SUPPORTED_MODELS = {
    # Anthropic Claude models
    "claude-opus-4": {"provider": "anthropic", "available": True},
    "claude-opus-4-8": {"provider": "anthropic", "available": True},
    "claude-sonnet-4": {"provider": "anthropic", "available": True},
    "claude-sonnet-4-6": {"provider": "anthropic", "available": True},
    "claude-haiku-4": {"provider": "anthropic", "available": True},

    # Google Gemini models
    "gemini-3.5-flash": {"provider": "google", "available": True},
    "gemini-3.1-pro": {"provider": "google", "available": True},

    # OpenAI models (if supported)
    "gpt-4": {"provider": "openai", "available": False},
    "gpt-5": {"provider": "openai", "available": False},
}


def validate_model(model: str) -> bool:
    """Check if model is supported and available."""
    model_info = SUPPORTED_MODELS.get(model)
    if not model_info:
        return False
    return model_info.get("available", False)


def get_model_provider(model: str) -> str:
    """Get provider for a model."""
    model_info = SUPPORTED_MODELS.get(model, {})
    return model_info.get("provider", "unknown")


def list_available_models(provider: str = None) -> List[str]:
    """List all available models, optionally filtered by provider."""
    models = [
        model for model, info in SUPPORTED_MODELS.items()
        if info.get("available") and (not provider or info.get("provider") == provider)
    ]
    return sorted(models)
