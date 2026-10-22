"""Validate and decode bounded uploads before starting model inference."""

from __future__ import annotations

from pathlib import Path


def validate_audio(path: Path, max_seconds: float) -> None:
    import av

    try:
        duration = 0.0
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise ValueError("O arquivo não contém uma faixa de áudio.")
            for frame in container.decode(audio=0):
                duration += frame.samples / frame.sample_rate
                if duration > max_seconds:
                    raise ValueError(f"O áudio deve ter no máximo {max_seconds:g} segundos.")
        if duration <= 0:
            raise ValueError("O áudio está vazio.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Não foi possível decodificar o áudio enviado.") from exc
