"""
Anthropic API client integration.
"""
import os
from typing import Optional, Dict, Any
from anthropic import Anthropic


class AnthropicClient:
    """Wrapper for Anthropic API."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Anthropic client.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")

        self.client = Anthropic(api_key=self.api_key)

    def create_message(
        self,
        model: str,
        messages: list,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Create a message using Anthropic API.

        Args:
            model: Model name (e.g., "claude-opus-4")
            messages: List of message dicts
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional API parameters

        Returns:
            API response dict
        """
        response = self.client.messages.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        return {
            "id": response.id,
            "model": response.model,
            "content": response.content[0].text if response.content else "",
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "stop_reason": response.stop_reason,
        }
