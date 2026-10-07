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
        self,
        directory: Path,
        manifest: Mapping[str, object],
        *,
        run_id: str | None = None,
        data_directory: Path | None = None,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or uuid4().hex
        self.path = directory / f"{self.run_id}.jsonl"
        self._stream = self.path.open("x", encoding="utf-8")
        self._started = time.perf_counter()
        self._sequence = 0
        self._lock = threading.Lock()
        self._data_directory = data_directory
        self._instruction: str | None = None
        self._transcription: str | None = None
        self._data_normalization: dict[str, object] | None = None
        self._data_extraction: dict[str, object] | None = None
        self._initial_fields: list[dict[str, object]] = []
        self._final_fields: list[dict[str, object]] = []
        self._written_fields: dict[str, object] = {}
        self._form_url: str | None = None
        self._verification_complete: bool | None = None
        self._submitted: bool | None = None
        self._completed: dict[str, object] = {}
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
            if self._data_directory is not None:
                self._remember(name, data)

    def _remember(self, name: str, data: Mapping[str, object]) -> None:
        if name == "form_started":
            self._instruction = str(data.get("instruction", ""))
        elif name == "audio_transcribed":
            self._transcription = str(data.get("text", ""))
        elif name == "data_normalized":
            self._data_normalization = dict(data)
        elif name == "data_extracted":
            self._data_extraction = dict(data)
        elif name == "form_inspected":
            fields = data.get("fields")
            if isinstance(fields, list):
                self._initial_fields = [dict(field) for field in fields if isinstance(field, dict)]
        elif name == "fill_field_completed":
            output = data.get("output")
            if isinstance(output, dict) and output.get("success") is True:
                reference = output.get("field_ref") or output.get("field")
                if reference is not None:
                    self._written_fields[str(reference)] = output.get("value")
        elif name == "form_completed":
            inspection = data.get("final_inspection")
            if isinstance(inspection, dict):
                self._form_url = str(inspection.get("url", ""))
                fields = inspection.get("fields")
                if isinstance(fields, list):
                    self._final_fields = [
                        dict(field) for field in fields if isinstance(field, dict)
                    ]
            complete = data.get("verification_complete")
            self._verification_complete = complete if isinstance(complete, bool) else None
            submitted = data.get("submitted")
            self._submitted = submitted if isinstance(submitted, bool) else None
        elif name == "run_completed":
            self._completed = dict(data)

    def _save_form_data(self) -> None:
        if self._data_directory is None:
            return
        before = {
            str(field.get("id") or field.get("name") or field.get("label")): field.get("value")
            for field in self._initial_fields
        }
        current = {
            str(field.get("id") or field.get("name") or field.get("label")): field.get("value")
            for field in self._final_fields
        }
        filled = {
            reference: value
            for reference, value in current.items()
            if reference not in before or before[reference] != value
        }
        if not self._final_fields:
            filled = dict(self._written_fields)
            current = dict(filled)
        evaluation = {
            key: self._completed[key]
            for key in (
                "id",
                "attempt",
                "mode",
                "passed",
                "expected_data",
                "returned_data",
                "error_codes",
            )
            if key in self._completed
        }
        human_submission = self._completed.get("human_submission")
        submitted = self._completed.get("submitted", self._submitted)
        if isinstance(human_submission, dict) and human_submission.get("submitted") is True:
            submitted = True
        data = {
            "run_id": self.run_id,
            "trace_path": str(self.path),
            "instruction": self._instruction or self._completed.get("instruction"),
            "transcription": self._transcription,
            "data_normalization": self._data_normalization,
            "data_extraction": self._data_extraction,
            "form_url": self._form_url,
            "filled_fields": filled,
            "form_fields": current,
            "verification_complete": self._verification_complete,
            "submitted": submitted,
            "evaluation": evaluation or None,
        }
        run_directory = self._data_directory / self.run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        (run_directory / "form_data.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )

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
            self._save_form_data()
