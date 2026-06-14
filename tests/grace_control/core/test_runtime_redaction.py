"""Tests for RuntimeRedactor."""
from __future__ import annotations

from grace_control.core.runtime_redaction import RuntimeRedactor


class TestRuntimeRedactor:

    def test_redactor_redacts_api_keys_tokens_secrets(self):
        redactor = RuntimeRedactor()
        env = {
            "OPENAI_API_KEY": "sk-abc123",
            "ANTHROPIC_API_KEY": "sk-ant-xyz",
            "GEMINI_API_KEY": "gemini-key",
            "DEEPSEEK_API_KEY": "dsk-key",
            "MY_TOKEN": "tok-123",
            "MY_SECRET": "secret-value",
            "PASSWORD": "hunter2",
            "COOKIE": "session=abc",
            "SAFE_VAR": "hello",
            "DB_URL": "postgresql://localhost",
        }
        result = redactor.redact_env(env)
        # Sensitive keys should be redacted
        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                     "DEEPSEEK_API_KEY", "MY_TOKEN", "MY_SECRET", "PASSWORD", "COOKIE"]:
            assert key in result
            assert result[key] == {"present": True, "redacted": True}, f"{key} not redacted"

        # Safe keys should pass through
        assert result["SAFE_VAR"] == "hello"
        assert result["DB_URL"] == "postgresql://localhost"

    def test_redact_env_empty(self):
        redactor = RuntimeRedactor()
        assert redactor.redact_env(None) == {}
        assert redactor.redact_env({}) == {}

    def test_redact_payload_nested_dict(self):
        redactor = RuntimeRedactor()
        payload = {
            "config": {
                "api_key": "sk-xxx",
                "normal_setting": "value",
            },
            "secrets": {
                "my_token": "tok-xxx",
            },
        }
        result = redactor.redact_payload(payload)
        assert result["config"]["api_key"] == {"present": True, "redacted": True}
        assert result["config"]["normal_setting"] == "value"
        assert result["secrets"]["my_token"] == {"present": True, "redacted": True}

    def test_redact_payload_list_of_dicts(self):
        redactor = RuntimeRedactor()
        payload = {
            "items": [
                {"name": "item1", "api_key": "sk-xxx"},
                {"name": "item2", "my_token": "tok-xxx"},
            ]
        }
        result = redactor.redact_payload(payload)
        assert result["items"][0]["api_key"] == {"present": True, "redacted": True}
        assert result["items"][0]["name"] == "item1"
        assert result["items"][1]["my_token"] == {"present": True, "redacted": True}
