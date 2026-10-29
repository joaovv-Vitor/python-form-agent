"""Load and validate application configuration."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .core.errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_PROFILES_FILE = PROJECT_ROOT / "model-profiles.json"
API_KEY_PLACEHOLDERS = {
    "coloque_sua_chave_aqui",
    "sua_chave_aqui",
    "your_api_key_here",
    "changeme",
}


@dataclass(frozen=True, slots=True)
class ModelConfig:
    profile: str
    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str | None = None
    timeout_seconds: float = 60.0
    temperature: float | None = None
    max_retries: int = 0
    prompt_version: str = "form-agent-v2"


@dataclass(frozen=True, slots=True)
class BrowserConfig:
    url: str
    headless: bool = True
    timeout_ms: float = 30_000
    executable_path: str | None = None
    submission_success_selector: str = '[data-form-agent-submitted="true"]'
    form_selector: str | None = None
    restrict_network: bool = False
    allowed_hosts: tuple[str, ...] = ()


def _positive_float(value: str, variable: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{variable} deve ser um número.") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ConfigurationError(f"{variable} deve ser maior que zero.")
    return parsed


def parse_boolean(value: str, variable: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "sim", "yes", "on"}:
        return True
    if normalized in {"0", "false", "não", "nao", "no", "off"}:
        return False
    raise ConfigurationError(f"{variable} deve ser true ou false.")


def _load_environment(env_file: Path | None) -> None:
    if env_file is not None:
        load_dotenv(env_file, override=False)


def _read_profiles(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Arquivo de perfis não encontrado: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"JSON inválido no arquivo de perfis: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise ConfigurationError("model-profiles.json deve conter um objeto 'profiles'.")
    return data


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"Configuração obrigatória ausente: {label}.")
    return value.strip()


def load_model_config(
    *,
    env_file: Path | None = DEFAULT_ENV_FILE,
    profiles_file: Path | None = None,
    profile_name: str | None = None,
    variable_prefix: str = "LLM",
) -> ModelConfig:
    _load_environment(env_file)
    path = profiles_file or Path(os.getenv("MODEL_PROFILES_FILE", str(DEFAULT_PROFILES_FILE)))
    data = _read_profiles(path)
    profile_name = (
        profile_name
        or os.getenv("MODEL_PROFILE")
        or _required_text(data.get("defaultProfile"), "defaultProfile")
    )
    profiles = data["profiles"]
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        available = ", ".join(sorted(profiles)) or "nenhum"
        raise ConfigurationError(
            f"Perfil de modelo desconhecido: {profile_name}. Disponíveis: {available}."
        )

    provider = _required_text(profile.get("provider"), f"profiles.{profile_name}.provider")
    model = os.getenv(f"{variable_prefix}_MODEL") or _required_text(
        profile.get("model"), f"profiles.{profile_name}.model"
    )
    api_key_env = _required_text(profile.get("apiKeyEnv"), f"profiles.{profile_name}.apiKeyEnv")
    api_key = (os.getenv(f"{variable_prefix}_API_KEY") or os.getenv(api_key_env) or "").strip()
    if not api_key:
        raise ConfigurationError(
            f"Chave ausente: defina {api_key_env} ou {variable_prefix}_API_KEY no arquivo .env."
        )
    if api_key.lower() in API_KEY_PLACEHOLDERS:
        raise ConfigurationError(
            f"Substitua o valor de exemplo de {api_key_env} por uma chave válida no arquivo .env."
        )

    configured_base_url = os.getenv(f"{variable_prefix}_BASE_URL")
    profile_base_url = profile.get("baseURL")
    base_url = configured_base_url or (str(profile_base_url).strip() if profile_base_url else None)
    timeout_variable = f"{variable_prefix}_TIMEOUT_SECONDS"
    timeout = _positive_float(os.getenv(timeout_variable, "60"), timeout_variable)
    temperature_variable = f"{variable_prefix}_TEMPERATURE"
    temperature_raw = os.getenv(temperature_variable)
    temperature = None
    if temperature_raw:
        try:
            temperature = float(temperature_raw)
        except ValueError as exc:
            raise ConfigurationError(f"{temperature_variable} deve ser um número.") from exc
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ConfigurationError(f"{temperature_variable} deve estar entre 0 e 2.")
    return ModelConfig(
        profile=profile_name,
        provider=provider,
        model=model.strip(),
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout,
        temperature=temperature,
        prompt_version=os.getenv("FORM_PROMPT_VERSION", "form-agent-v2"),
    )


def load_browser_config(*, env_file: Path | None = DEFAULT_ENV_FILE) -> BrowserConfig:
    _load_environment(env_file)
    default_url = (PROJECT_ROOT / "examples/test-form/index.html").as_uri()
    url = (os.getenv("FORM_URL") or default_url).strip()
    if not url:
        raise ConfigurationError("FORM_URL não pode ser vazio.")
    headless = parse_boolean(os.getenv("HEADLESS", "true"), "HEADLESS")
    timeout_ms = _positive_float(os.getenv("BROWSER_TIMEOUT_MS", "30000"), "BROWSER_TIMEOUT_MS")
    executable_path = (os.getenv("BROWSER_EXECUTABLE_PATH") or "").strip() or None
    return BrowserConfig(
        url=url,
        headless=headless,
        timeout_ms=timeout_ms,
        executable_path=executable_path,
        submission_success_selector=os.getenv(
            "SUBMISSION_SUCCESS_SELECTOR", '[data-form-agent-submitted="true"]'
        ),
        form_selector=os.getenv("FORM_SELECTOR") or None,
        restrict_network=parse_boolean(
            os.getenv("BROWSER_RESTRICT_NETWORK", "false"), "BROWSER_RESTRICT_NETWORK"
        ),
        allowed_hosts=tuple(
            host.strip()
            for host in os.getenv("BROWSER_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        ),
    )


def load_agent_max_turns(*, env_file: Path | None = DEFAULT_ENV_FILE) -> int:
    _load_environment(env_file)
    raw_value = os.getenv("AGENT_MAX_TURNS", "8")
    try:
        max_turns = int(raw_value)
    except ValueError as exc:
        raise ConfigurationError("AGENT_MAX_TURNS deve ser um número inteiro.") from exc
    if max_turns <= 0:
        raise ConfigurationError("AGENT_MAX_TURNS deve ser maior que zero.")
    return max_turns
