"""
API key management.
"""
import os
from typing import Optional, Dict


def get_anthropic_api_key() -> Optional[str]:
    """Get Anthropic API key from environment."""
    return os.environ.get("ANTHROPIC_API_KEY")


def get_google_api_key() -> Optional[str]:
    """Get Google API key from environment."""
    return os.environ.get("GOOGLE_API_KEY")


def validate_api_keys() -> Dict[str, bool]:
    """Validate that required API keys are present."""
    return {
        "anthropic": bool(get_anthropic_api_key()),
        "google": bool(get_google_api_key()),
    }
