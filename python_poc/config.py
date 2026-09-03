from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ModelConfig:
    profile: str
    provider: str
    model: str
    api_key: str
    base_url: str | None = None


def load_model_config() -> ModelConfig:
    load_dotenv(PROJECT_ROOT / ".env")
    path = Path(os.getenv("MODEL_PROFILES_FILE", str(PROJECT_ROOT / "model-profiles.json")))
    data = json.loads(path.read_text(encoding="utf-8"))
    profile_name = os.getenv("MODEL_PROFILE", data["defaultProfile"])
    try:
        profile = data["profiles"][profile_name]
    except KeyError as exc:
        raise ValueError(f"Perfil de modelo desconhecido: {profile_name}") from exc
    api_key = os.getenv("LLM_API_KEY") or os.getenv(profile["apiKeyEnv"])
    if not api_key:
        raise ValueError(f"Chave ausente: defina {profile['apiKeyEnv']} ou LLM_API_KEY")
    return ModelConfig(
        profile=profile_name,
        provider=profile["provider"],
        model=os.getenv("LLM_MODEL", profile["model"]),
        base_url=os.getenv("LLM_BASE_URL", profile.get("baseURL")),
        api_key=api_key,
    )
