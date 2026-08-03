import os
from dataclasses import dataclass


DEFAULT_VEO_MODEL = "veo-3.1-lite-generate-preview"


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    orchestrator_api_key: str | None
    veo_model: str


def load_settings() -> Settings:
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        orchestrator_api_key=os.getenv("ORCHESTRATOR_API_KEY") or None,
        veo_model=os.getenv("VEO_MODEL", DEFAULT_VEO_MODEL),
    )
