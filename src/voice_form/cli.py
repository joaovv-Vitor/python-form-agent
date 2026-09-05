"""CLI for audio → transcription → form, with optional post-fill human confirmation."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from audio_agent.agent import AudioAgent
from audio_agent.cli import add_transcription_arguments, settings_from_arguments
from audio_agent.engines import FasterWhisperSpeechToTextEngine
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.bootstrap import create_application
from form_agent.config import PROJECT_ROOT, load_browser_config
from form_agent.confirmation import confirm_submission
from form_agent.core.agent import submission_denied
from form_agent.core.errors import FormAgentError
from form_agent.experiments import RunTrace, metadata

from .pipeline import AudioFormPipeline


async def run(arguments: argparse.Namespace) -> int:
    settings = settings_from_arguments(arguments)
    application = create_application()
    try:
        manifest = metadata(
            model=application.config,
            browser=load_browser_config(),
            audio_file=arguments.audio_file,
            stt_settings=settings.to_dict(),
            max_turns=application.agent.max_turns,
        )
        with RunTrace(arguments.trace_directory, manifest) as trace:
            application.agent.events = trace.emit
            pipeline = AudioFormPipeline(
                AudioAgent(AudioPreprocessor(), FasterWhisperSpeechToTextEngine()),
                application.agent,
                events=trace.emit,
            )
            result = await pipeline.run(arguments.audio_file, settings)
            if arguments.json:
                print(
                    json.dumps(
                        {**result.to_dict(), "run_id": trace.run_id, "trace_path": str(trace.path)},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                if result.transcription:
                    print(f"Transcrição: {result.transcription.text}")
                if result.form:
                    print(result.form.message)
                else:
                    print("; ".join(f"{issue.code}: {issue.message}" for issue in result.issues))
            if arguments.confirm_submit and result.form and result.transcription:
                if submission_denied(result.transcription.text):
                    trace.emit(
                        "run_completed",
                        {**result.to_dict(), "human_submission": "denied_by_instruction"},
                    )
                    print("Envio bloqueado pela instrução negativa.")
                    return 2
                output = await confirm_submission(application, result.form)
                trace.emit("human_submission", output)
                trace.emit("run_completed", {**result.to_dict(), "human_submission": output})
                print(json.dumps(output, ensure_ascii=False))
                return 0 if output.get("submitted") is True else 2
            trace.emit("run_completed", result.to_dict())
            return (
                0
                if result.form
                and result.form.verification_complete
                and not result.form.turn_limit_reached
                and all(issue.code == "SUBMISSION_BLOCKED" for issue in result.issues)
                else 2
            )
    finally:
        await application.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preenche formulário a partir de um arquivo de áudio."
    )
    parser.add_argument("audio_file", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--trace-directory", type=Path, default=PROJECT_ROOT / "reports/runs")
    parser.add_argument(
        "--confirm-submit",
        action="store_true",
        help="Pede confirmação humana após preencher; não autoriza o LLM.",
    )
    add_transcription_arguments(parser)
    arguments = parser.parse_args(argv)
    if arguments.json and arguments.confirm_submit:
        parser.error("--json e --confirm-submit não podem ser combinados")
    try:
        return asyncio.run(run(arguments))
    except (FormAgentError, ValueError) as exc:
        print(f"Erro: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
