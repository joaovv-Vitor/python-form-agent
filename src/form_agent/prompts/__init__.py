"""Versioned, packaged prompts used as experimental inputs."""

import re
from importlib.resources import files

from ..core.errors import ConfigurationError


def load_prompt(version: str) -> str:
    if not re.fullmatch(r"form-agent-v[1-9][0-9]*", version):
        raise ConfigurationError("Versão de prompt inválida.")
    resource = files(__package__).joinpath(f"{version}.txt")
    if not resource.is_file():
        raise ConfigurationError(f"Prompt não encontrado: {version}")
    return resource.read_text(encoding="utf-8").strip()
