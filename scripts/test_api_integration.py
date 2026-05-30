#!/usr/bin/env python3
"""
Test Anthropic API integration.

This script tests the Anthropic API client with a simple message.
Requires ANTHROPIC_API_KEY environment variable to be set.
"""
import sys
import os

# Add src to path for local testing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from prefect_grace.platform.anthropic_client import AnthropicClient
from prefect_grace.platform.api_keys import validate_api_keys
from prefect_grace.platform.model_validator import list_available_models


def main():
    """Test Anthropic API integration."""
    print("=" * 60)
    print("GRACE Orchestrator - API Integration Test")
    print("=" * 60)
    print()

    # Check API keys
    print("1. Checking API keys...")
    keys = validate_api_keys()
    print(f"   Anthropic API key: {'✓ Present' if keys['anthropic'] else '✗ Missing'}")
    print(f"   Google API key: {'✓ Present' if keys['google'] else '✗ Missing'}")
    print()

    if not keys['anthropic']:
        print("ERROR: ANTHROPIC_API_KEY not set")
        print("Set it with: export ANTHROPIC_API_KEY='sk-ant-...'")
        return 1

    # List available models
    print("2. Available models:")
    models = list_available_models()
    for model in models:
        print(f"   - {model}")
    print()

    # Test Anthropic client
    print("3. Testing Anthropic API client...")
    try:
        client = AnthropicClient()
        print("   ✓ Client initialized")

        print("   Sending test message to claude-sonnet-4-6...")
        response = client.create_message(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "Say 'Hello from GRACE!' and nothing else."}],
            max_tokens=100
        )

        print(f"   ✓ Response received")
        print(f"   Message ID: {response['id']}")
        print(f"   Model: {response['model']}")
        print(f"   Content: {response['content']}")
        print(f"   Tokens: {response['usage']['input_tokens']} in, {response['usage']['output_tokens']} out")
        print()

        print("=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"   ✗ Error: {e}")
        print()
        print("=" * 60)
        print("✗ Test failed")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
