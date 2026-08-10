from types import SimpleNamespace

import pytest
from google.genai import models

from app.providers import GoogleVeoProvider, build_veo_config


def test_veo_config_converts_for_gemini_api_without_network() -> None:
    config = build_veo_config()
    request: dict[str, object] = {}

    models._GenerateVideosConfig_to_mldev(config, request, config)

    assert config.generate_audio is None
    assert request == {
        "parameters": {
            "sampleCount": 1,
            "resolution": "720p",
            "aspectRatio": "16:9",
            "durationSeconds": 8,
        }
    }


@pytest.mark.parametrize(
    ("status_code", "message", "expected_code"),
    [
        (401, "invalid credentials", "authentication_failed"),
        (403, "permission denied", "authentication_failed"),
        (429, "quota exhausted", "quota_exceeded"),
        (400, "prompt blocked by safety policy", "safety_rejected"),
        (503, "service unavailable", "provider_unavailable"),
        (422, "unexpected provider response", "provider_error"),
    ],
)
def test_google_errors_are_normalized(status_code: int, message: str, expected_code: str) -> None:
    raw_error = SimpleNamespace(code=status_code, message=message)
    normalized = GoogleVeoProvider._normalize_api_error(raw_error)  # type: ignore[arg-type]
    assert normalized.code == expected_code
    assert message not in normalized.public_message
