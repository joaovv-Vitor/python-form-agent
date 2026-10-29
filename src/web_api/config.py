"""Web runtime and bounded resource settings for the homelab."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from dotenv import load_dotenv

from audio_agent.cli import EMAIL_HOTWORDS, EMAIL_INITIAL_PROMPT
from audio_agent.models import TranscriptionSettings
from form_agent.config import DEFAULT_ENV_FILE


def asset(name: str) -> Path:
    return Path(str(files("web_api").joinpath("assets", name)))


@dataclass(frozen=True)
class WebConfig:
    data_dir: Path = Path("reports/web")
    frontend_dir: Path = Path("frontend/dist")
    max_sessions: int = 1
    max_upload_bytes: int = 25 * 1024 * 1024
    max_audio_seconds: float = 120
    idle_seconds: float = 900
    operation_seconds: float = 600
    event_buffer: int = 128
    cookie_secure: bool = False
    public_origin: str = ""
    allowed_form_hosts: tuple[str, ...] = ()
    settings: TranscriptionSettings = field(
        default_factory=lambda: TranscriptionSettings(
            model="large-v3",
            language="pt",
            device="cpu",
            compute_type="int8",
            initial_prompt=EMAIL_INITIAL_PROMPT,
            hotwords=EMAIL_HOTWORDS,
        )
    )

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value)
            for value in (self.max_audio_seconds, self.idle_seconds, self.operation_seconds)
        ):
            raise ValueError("Os limites web devem ser finitos.")
        if (
            min(
                self.max_sessions,
                self.max_upload_bytes,
                self.max_audio_seconds,
                self.idle_seconds,
                self.operation_seconds,
                self.event_buffer,
            )
            <= 0
        ):
            raise ValueError("Os limites web devem ser positivos.")

    @classmethod
    def from_env(cls) -> WebConfig:
        load_dotenv(DEFAULT_ENV_FILE, override=False)
        return cls(
            data_dir=Path(os.getenv("WEB_DATA_DIR", "reports/web")),
            frontend_dir=Path(os.getenv("WEB_FRONTEND_DIR", "frontend/dist")),
            max_sessions=int(os.getenv("WEB_MAX_SESSIONS", "1")),
            max_upload_bytes=int(os.getenv("WEB_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
            max_audio_seconds=float(os.getenv("WEB_MAX_AUDIO_SECONDS", "120")),
            idle_seconds=float(os.getenv("WEB_IDLE_SECONDS", "900")),
            operation_seconds=float(os.getenv("WEB_OPERATION_SECONDS", "600")),
            cookie_secure=os.getenv("WEB_COOKIE_SECURE", "false").lower() == "true",
            public_origin=os.getenv("WEB_PUBLIC_ORIGIN", "").rstrip("/"),
            allowed_form_hosts=tuple(
                host.strip().lower()
                for host in os.getenv("WEB_ALLOWED_FORM_HOSTS", "").split(",")
                if host.strip()
            ),
            settings=TranscriptionSettings(
                model=os.getenv("WEB_STT_MODEL", "large-v3"),
                language="pt",
                device="cpu",
                compute_type="int8",
                initial_prompt=EMAIL_INITIAL_PROMPT,
                hotwords=EMAIL_HOTWORDS,
            ),
        )
