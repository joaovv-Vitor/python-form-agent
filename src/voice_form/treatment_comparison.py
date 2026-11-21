"""Compare treatments on the selected Whisper's saved, immutable transcriptions."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from audio_agent.agent import AudioAgent
from audio_agent.models import (
    EngineTranscription,
    PreparedAudio,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionSettings,
)
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.bootstrap import create_application
from form_agent.config import load_agent_max_turns, load_browser_config, load_model_config
from form_agent.evaluation.cases import load_audio_cases
from form_agent.evaluation.comparison import COMPARISON_VERSION
from form_agent.evaluation.metrics import EvaluationRow
from form_agent.evaluation.reporting import write_reports
from form_agent.experiments import RunTrace, metadata, sha256_file

from .evaluation import run_audio_attempt, summarize
from .extraction import create_extractor
from .normalization import DATA_NORMALIZATION_VERSION
from .pipeline import DataTreatment

CONDITIONS: tuple[DataTreatment, ...] = ("raw", "rules", "deepseek")


class SavedTranscriptionsOnly:
    def transcribe(
        self, audio: PreparedAudio, settings: TranscriptionSettings
    ) -> EngineTranscription:
        raise RuntimeError("STT desabilitado: esta rodada exige transcrições compartilhadas salvas")


def restore_transcription(data: dict[str, Any]) -> TranscriptionResult:
    values = dict(data)
    values["audio_file"] = Path(data["audio_file"])
    values["executed_at"] = datetime.fromisoformat(data["executed_at"])
    values["settings"] = TranscriptionSettings(**data["settings"])
    values["segments"] = tuple(TranscriptionSegment(**segment) for segment in data["segments"])
    result = TranscriptionResult(**values)
    if result.to_dict() != data:
        raise ValueError("A restauração alterou a transcrição salva")
    return result


def load_shared(
    directory: Path,
) -> tuple[dict[str, Any], dict[tuple[str, int], TranscriptionResult], dict[str, str]]:
    index = json.loads((directory / "index.json").read_text())
    selected = index["selected_model"]
    transcriptions: dict[tuple[str, int], TranscriptionResult] = {}
    hashes: dict[str, str] = {}
    for item in index["transcriptions"]:
        path = directory / item["file"]
        if path.parent.resolve() != directory.resolve() or sha256_file(path) != item["sha256"]:
            raise ValueError("Arquivo de transcrição fora do catálogo ou com hash divergente")
        payload = json.loads(path.read_text())
        key = (item["case_id"], item["attempt"])
        if key in transcriptions or (payload["case_id"], payload["attempt"]) != key:
            raise ValueError("Identificação de transcrição duplicada ou divergente")
        transcription = restore_transcription(payload["transcription"])
        if transcription.model != selected or transcription.settings.model != selected:
            raise ValueError("A transcrição não pertence ao Whisper selecionado")
        transcriptions[key] = transcription
        hashes[f"{key[0]}:{key[1]}"] = item["sha256"]
    return index, transcriptions, hashes


def condition_summary(rows: list[EvaluationRow]) -> dict[str, float | int]:
    metrics = summarize(rows)
    post = [row.post_stt_seconds for row in rows if row.post_stt_seconds is not None]
    if post:
        metrics["average_post_stt_seconds"] = sum(post) / len(post)
    metrics["presentation_differences"] = sum(len(row.presentation_differences) for row in rows)
    metrics["pending_fields"] = sum(len(row.pending_fields) for row in rows)
    metrics["extraction_prompt_tokens"] = sum(row.extraction_prompt_tokens or 0 for row in rows)
    metrics["extraction_completion_tokens"] = sum(
        row.extraction_completion_tokens or 0 for row in rows
    )
    return metrics


def finish(rows: list[EvaluationRow], output: Path, total: int) -> dict[str, Any]:
    assert len(rows) == total
    assert len({(r.id, r.attempt, r.data_treatment) for r in rows}) == total
    assert not any(r.submitted or r.submission_attempted for r in rows)
    for pair in {r.pair_id for r in rows}:
        group = [r for r in rows if r.pair_id == pair]
        assert {r.data_treatment for r in group} == set(CONDITIONS)
        assert len({r.transcription for r in group}) == 1
        assert len({(r.wer, r.word_edits, r.reference_words) for r in group}) == 1
    summaries = {
        condition: condition_summary([r for r in rows if r.data_treatment == condition])
        for condition in CONDITIONS
    }
    ranking = sorted(
        CONDITIONS,
        key=lambda name: (
            -summaries[name]["complete_success_rate"],
            -summaries[name]["field_accuracy_rate"],
            summaries[name].get("average_post_stt_seconds", float("inf")),
        ),
    )
    for condition in CONDITIONS:
        write_reports(
            summaries[condition],
            [r for r in rows if r.data_treatment == condition],
            condition,
            output / "reports" / condition,
        )
    write_reports(
        {
            f"{name}.{key}": value
            for name, values in summaries.items()
            for key, value in values.items()
        },
        rows,
        "treatment-comparison",
        output / "reports",
    )
    by_case = {
        condition: {
            case: condition_summary(
                [r for r in rows if r.data_treatment == condition and r.id == case]
            )
            for case in sorted({r.id for r in rows})
        }
        for condition in CONDITIONS
    }
    result = {
        "total_attempts": total,
        "pairs": len({r.pair_id for r in rows}),
        "stt_executions": 0,
        "comparison_version": COMPARISON_VERSION,
        "by_treatment": summaries,
        "by_case": by_case,
        "ranking": ranking,
        "best_observed_treatment": ranking[0],
    }
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    lines = [
        "# Rodada 2 — Comparação dos tratamentos",
        "",
        f"{total} preenchimentos em pares, usando transcrições salvas do large-v3, agente DeepSeek V4 Flash e comparação {COMPARISON_VERSION}.",
        "",
        "| Tratamento | Acerto por campo | Sucesso completo | WER | Falhas operacionais | Tempo pós-STT médio (s) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for condition, metrics in summaries.items():
        lines.append(
            f"| {condition} | {metrics['field_accuracy_rate']:.2%} | {metrics['complete_success_rate']:.2%} | {metrics.get('wer', float('nan')):.2%} | {metrics['operational_failure_rate']:.2%} | {metrics.get('average_post_stt_seconds', float('nan')):.2f} |"
        )
    lines += [
        "",
        f"**Melhor resultado observado nesta amostra: {ranking[0]}.**",
        "Critério fixado: maior sucesso completo, maior acerto por campo e menor tempo pós-STT para desempate.",
        "",
        "A WER é igual entre tratamentos por construção: cada caso/tentativa usa a mesma transcrição integral. Não houve nova inferência Whisper.",
        "O tempo comparativo é o pós-STT: tratamento, inspeção e preenchimento. `total_seconds` e `stt_seconds` preservam o tempo STT histórico da rodada 1, que não foi executado nesta rodada.",
        "Amostra de cinco áudios com três repetições, sem envio de respostas.",
        "",
        "## Por formulário",
        "",
        "| Tratamento | Formulário | Acerto por campo | Sucesso completo |",
        "| --- | --- | --- | --- |",
    ]
    for condition, groups in by_case.items():
        for case, metrics in groups.items():
            lines.append(
                f"| {condition} | {case} | {metrics['field_accuracy_rate']:.2%} | {metrics['complete_success_rate']:.2%} |"
            )
    lines += [
        "",
        "## Artefatos",
        "",
        "- [Protocolo](protocol.md)",
        "- [Configuração congelada](protocol.json)",
        "- [Resumo JSON](summary.json)",
        "- [Relatório HTML](reports/python-evaluation-report_treatment-comparison.html)",
        "- [Relatório CSV](reports/python-evaluation-report_treatment-comparison.csv)",
        "- [Índice de tentativas](rows.jsonl)",
        "",
        "As diferenças de apresentação aceitas ficam em presentation_differences, preservando o conteúdo observado no DOM.",
        "",
    ]
    (output / "resumo.md").write_text("\n".join(lines))
    return result


async def compare(
    cases_path: Path, shared_directory: Path, output: Path, attempts: int = 3
) -> dict[str, Any]:
    if attempts <= 0:
        raise ValueError("attempts deve ser positivo")
    cases = load_audio_cases(cases_path)
    if any(case.submitted or case.submission_authorized for case in cases):
        raise ValueError("A rodada requer envio desabilitado")
    shared_index, transcriptions, shared_hashes = load_shared(shared_directory)
    expected = {(case.id, attempt) for case in cases for attempt in range(1, attempts + 1)}
    if set(transcriptions) != expected or shared_index["selected_model"] != "large-v3":
        raise ValueError("O conjunto de transcrições não cobre os pares esperados do large-v3")
    output.mkdir(parents=True, exist_ok=True)
    model_config, browser_config = load_model_config(), load_browser_config()
    if model_config.model != "deepseek-v4-flash":
        raise ValueError("O agente deve permanecer deepseek-v4-flash")
    max_turns = load_agent_max_turns()
    extractor = create_extractor()
    try:
        fingerprint = metadata(
            model=model_config, browser=browser_config, case_file=cases_path, max_turns=max_turns
        )
        audio_hashes = {
            case.id: sha256_file(case.audio_file) if case.audio_file else None for case in cases
        }
        previous_path = output / "round1_protocol.json"
        if previous_path.exists():
            previous = json.loads(previous_path.read_text())
            if (
                previous["llm"] != fingerprint["llm"]
                or previous["catalog_sha256"] != fingerprint["case_file_sha256"]
                or previous["audio_sha256"] != audio_hashes
                or previous["comparison_version"] != COMPARISON_VERSION
                or previous["max_turns"] != max_turns
                or previous["browser"] != fingerprint.get("browser")
            ):
                raise ValueError(
                    "Agente, catálogo, áudio, navegador ou avaliação divergente da rodada 1"
                )
        settings_set = {
            json.dumps(t.settings.to_dict(), sort_keys=True) for t in transcriptions.values()
        }
        if len(settings_set) != 1:
            raise ValueError("As transcrições usam configurações Whisper diferentes")
        protocol = {
            "source_sha256": fingerprint["source_sha256"],
            "catalog_sha256": fingerprint["case_file_sha256"],
            "llm": fingerprint["llm"],
            "browser": fingerprint.get("browser"),
            "max_turns": max_turns,
            "audio_sha256": audio_hashes,
            "comparison_version": COMPARISON_VERSION,
            "selected_whisper": shared_index["selected_model"],
            "stt_settings": json.loads(next(iter(settings_set))),
            "shared_index_sha256": sha256_file(shared_directory / "index.json"),
            "shared_file_sha256": shared_hashes,
            "conditions": CONDITIONS,
            "attempts_per_case_condition": attempts,
            "stt_executions": 0,
            "extraction": extractor.manifest(),
            "rules_version": DATA_NORMALIZATION_VERSION,
            "submission_authorized": False,
            "ordering": "cyclic treatment rotation per case/attempt",
            "selection_order": [
                "complete_success_rate descending",
                "field_accuracy_rate descending",
                "average_post_stt_seconds ascending",
            ],
        }
        protocol_path = output / "protocol.json"
        serialized = json.dumps(protocol, ensure_ascii=False, indent=2)
        if protocol_path.exists() and json.loads(protocol_path.read_text()) != json.loads(
            serialized
        ):
            raise ValueError("O protocolo mudou; use uma nova pasta")
        if not protocol_path.exists():
            protocol_path.write_text(serialized)
        index = output / "rows.jsonl"
        rows = (
            [EvaluationRow(**json.loads(line)) for line in index.read_text().splitlines()]
            if index.exists()
            else []
        )
        completed = {(r.id, r.attempt, r.data_treatment) for r in rows}
        if len(completed) != len(rows):
            raise ValueError("Tentativas duplicadas no índice")
        audio = AudioAgent(AudioPreprocessor(), SavedTranscriptionsOnly())
        total = len(cases) * attempts * len(CONDITIONS)
        for case_index, case in enumerate(cases):
            for attempt in range(1, attempts + 1):
                transcription = transcriptions[(case.id, attempt)]
                shared_hash = shared_hashes[f"{case.id}:{attempt}"]
                pair_id = shared_hash[:24]
                offset = (case_index * attempts + attempt - 1) % len(CONDITIONS)
                order = CONDITIONS[offset:] + CONDITIONS[:offset]
                for position, condition in enumerate(order, 1):
                    if (case.id, attempt, condition) in completed:
                        continue
                    if sha256_file(cases_path) != protocol["catalog_sha256"]:
                        raise ValueError("O catálogo mudou durante a rodada")
                    browser = (
                        replace(browser_config, url=case.form_url)
                        if case.form_url
                        else browser_config
                    )
                    app = create_application(browser_config=browser, model_config=model_config)
                    app.agent.max_turns = max_turns
                    try:
                        manifest = metadata(
                            model=model_config,
                            browser=browser,
                            case_file=cases_path,
                            audio_file=case.audio_file,
                            stt_settings=transcription.settings.to_dict(),
                            max_turns=max_turns,
                        )
                        if (
                            manifest["source_sha256"] != protocol["source_sha256"]
                            or manifest["audio_sha256"] != audio_hashes[case.id]
                        ):
                            raise ValueError("Código ou áudio alterado durante a rodada")
                        manifest.update(
                            {
                                "experiment": "treatment-selection",
                                "mode": "pipeline",
                                "case_id": case.id,
                                "attempt": attempt,
                                "data_treatment": condition,
                                "pair_id": pair_id,
                                "condition_order": list(order),
                                "execution_index": position,
                                "allow_submission": False,
                                "comparison_version": COMPARISON_VERSION,
                                "shared_transcription_sha256": shared_hash,
                                "stt_reexecuted": False,
                                "data_normalization_version": DATA_NORMALIZATION_VERSION
                                if condition == "rules"
                                else None,
                                "extraction": extractor.manifest()
                                if condition == "deepseek"
                                else None,
                            }
                        )
                        print(
                            f"START {len(rows) + 1}/{total} {case.id} attempt={attempt} treatment={condition}",
                            flush=True,
                        )
                        with RunTrace(
                            output / "runs", manifest, data_directory=output / "evidence"
                        ) as trace:
                            app.agent.events = trace.emit
                            row = await run_audio_attempt(
                                case,
                                attempt,
                                "pipeline",
                                audio,
                                transcription.settings,
                                trace,
                                app,
                                allow_submission=False,
                                data_treatment=condition,
                                extractor=extractor if condition == "deepseek" else None,
                                prepared_transcription=transcription,
                                pair_id=pair_id,
                                condition_order=position,
                            )
                            assert not row.submitted and not row.submission_attempted
                            assert row.transcription == transcription.text
                        with index.open("a", encoding="utf-8") as stream:
                            stream.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
                        rows.append(row)
                        completed.add((case.id, attempt, condition))
                        print(
                            f"DONE {len(rows)}/{total} {condition} {row.correct}/{row.expected_count} success={row.functional_success} WER={row.wer} operational={row.operational_failure}",
                            flush=True,
                        )
                    finally:
                        await app.close()
        result = finish(rows, output, total)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return result
    finally:
        await extractor.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--shared-transcriptions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(compare(args.cases, args.shared_transcriptions, args.output, args.attempts))


if __name__ == "__main__":
    main()
