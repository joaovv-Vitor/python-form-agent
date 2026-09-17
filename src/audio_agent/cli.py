"""Command-line interface for file-based audio transcription."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from .agent import AudioAgent
from .engines import FasterWhisperSpeechToTextEngine
from .exceptions import AudioAgentError
from .models import TranscriptionResult, TranscriptionSettings
from .preprocessing import AudioPreprocessor

LOGGER = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcreve um arquivo de áudio local usando faster-whisper."
    )
    parser.add_argument("audio_file", type=Path, help="Caminho para WAV, MP3, MP4, M4A ou FLAC.")
    parser.add_argument("--json", action="store_true", help="Imprime o resultado em JSON.")
    add_transcription_arguments(parser)
    parser.add_argument("--verbose", action="store_true")
    return parser


def add_transcription_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model", default="small", help="Modelo Whisper a utilizar (padrão: small)."
    )
    parser.add_argument(
        "--language",
        help="Idioma esperado, como 'pt'. Sem esta opção, o idioma é detectado.",
    )
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--vad-filter", action="store_true")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def settings_from_arguments(arguments: argparse.Namespace) -> TranscriptionSettings:
    return TranscriptionSettings(
        model=arguments.model,
        language=arguments.language,
        device=arguments.device,
        compute_type=arguments.compute_type,
        beam_size=arguments.beam_size,
        temperature=arguments.temperature,
        vad_filter=arguments.vad_filter,
    )


def _print_human_result(result: TranscriptionResult) -> None:
    print(f"Arquivo: {result.audio_file}")
    print(f"Motor: {result.engine} {result.engine_version or '(versão desconhecida)'}")
    print(f"Modelo: {result.model}")
    print(f"Idioma: {result.language or 'não detectado'}")
    if result.language_probability is not None:
        print(f"Confiança do idioma: {result.language_probability:.2%}")
    if result.duration_seconds is not None:
        print(f"Duração: {result.duration_seconds:.2f}s")
    print(f"Tempo de processamento: {result.processing_time_seconds:.2f}s")
    print(f"Texto: {result.text}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    _configure_logging(arguments.verbose)
    try:
        settings = settings_from_arguments(arguments)
        agent = AudioAgent(AudioPreprocessor(), FasterWhisperSpeechToTextEngine())
        result = agent.transcribe(arguments.audio_file, settings)
    except (AudioAgentError, ValueError) as exc:
        LOGGER.debug("Falha durante a transcrição", exc_info=exc)
        print(f"Erro: {exc}")
        return 2

    if arguments.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_human_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
