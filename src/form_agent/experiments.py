"""Local JSONL traces and a small, secret-free experiment manifest."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from types import TracebackType
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from .config import PROJECT_ROOT, BrowserConfig, ModelConfig
from .prompts import load_prompt


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _git(*arguments: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *arguments],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def source_hash() -> str:
    digest = hashlib.sha256()
    paths = [
        *PROJECT_ROOT.joinpath("src").rglob("*.py"),
        *PROJECT_ROOT.joinpath("src").rglob("*.txt"),
        PROJECT_ROOT / "pyproject.toml",
    ]
    for path in sorted(paths):
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def metadata(
    *,
    model: ModelConfig | None = None,
    browser: BrowserConfig | None = None,
    case_file: Path | None = None,
    audio_file: Path | None = None,
    stt_settings: Mapping[str, object] | None = None,
    max_turns: int | None = None,
) -> dict[str, object]:
    status = _git("status", "--porcelain")
    result: dict[str, object] = {
        "schema_version": 1,
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": status != "" if status is not None else None,
        "source_sha256": source_hash(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "dependencies": {
            dist.metadata["Name"]: dist.version
            for dist in distributions()
            if dist.metadata.get("Name")
        },
        "case_file": str(case_file) if case_file else None,
        "case_file_sha256": sha256_file(case_file) if case_file else None,
        "audio_file": str(audio_file) if audio_file else None,
        "audio_sha256": sha256_file(audio_file) if audio_file else None,
        "stt_settings": dict(stt_settings) if stt_settings else None,
        "max_turns": max_turns,
    }
    if model:
        endpoint = urlsplit(model.base_url or "https://api.openai.com/v1")
        result["llm"] = {
            "profile": model.profile,
            "provider": model.provider,
            "model": model.model,
            "base_url": f"{endpoint.scheme}://{endpoint.hostname}{endpoint.path}",
            "temperature": model.temperature,
            "temperature_source": "provider_default" if model.temperature is None else "explicit",
            "max_retries": model.max_retries,
            "timeout_seconds": model.timeout_seconds,
            "prompt_version": model.prompt_version,
            "prompt_sha256": hashlib.sha256(load_prompt(model.prompt_version).encode()).hexdigest(),
        }
    if browser:
        url = urlsplit(browser.url)
        form_path = Path(unquote(url.path)) if url.scheme == "file" else None
        result["browser"] = {
            "url": browser.url,
            "form_sha256": sha256_file(form_path) if form_path else None,
            "headless": browser.headless,
            "timeout_ms": browser.timeout_ms,
            "executable_path": browser.executable_path,
            "submission_success_selector": browser.submission_success_selector,
        }
    return result


class RunTrace:
    def __init__(
        self, directory: Path, manifest: Mapping[str, object], *, run_id: str | None = None
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid4().hex
        self.path = directory / f"{self.run_id}.jsonl"
        self._stream = self.path.open("x", encoding="utf-8")
        self._started = time.perf_counter()
        self._sequence = 0
        self._lock = threading.Lock()
        self.emit("run_started", {"metadata": dict(manifest)})

    def emit(self, name: str, data: Mapping[str, object]) -> None:
        with self._lock:
            self._sequence += 1
            payload = {
                "schema_version": 1,
                "run_id": self.run_id,
                "sequence": self._sequence,
                "timestamp": datetime.now(UTC).isoformat(),
                "elapsed_seconds": time.perf_counter() - self._started,
                "event": name,
                "data": dict(data),
            }
            self._stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
            self._stream.flush()

    def __enter__(self) -> RunTrace:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if exc:
                self.emit("run_interrupted", {"error_type": type(exc).__name__})
            self.emit("trace_closed", {})
        finally:
            self._stream.close()
