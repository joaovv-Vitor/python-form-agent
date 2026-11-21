"""Compare Whisper models using isolated full-pipeline attempts and fixed scoring."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path

from audio_agent.agent import AudioAgent
from audio_agent.engines import FasterWhisperSpeechToTextEngine
from audio_agent.models import TranscriptionSettings
from audio_agent.preprocessing import AudioPreprocessor
from form_agent.bootstrap import create_application
from form_agent.config import load_agent_max_turns, load_browser_config, load_model_config
from form_agent.evaluation.cases import load_audio_cases
from form_agent.evaluation.comparison import COMPARISON_VERSION
from form_agent.evaluation.metrics import EvaluationRow
from form_agent.evaluation.reporting import write_reports
from form_agent.experiments import RunTrace, metadata, sha256_file

from .evaluation import run_audio_attempt, summarize
from .normalization import DATA_NORMALIZATION_VERSION

MODELS = ("base", "small", "medium", "large-v3")


def selection_key(metrics: dict[str, float | int]) -> tuple[float, ...]:
    return (
        -metrics["complete_success_rate"],
        -metrics["field_accuracy_rate"],
        metrics.get("wer", math.inf),
        metrics.get("average_stt_seconds", math.inf),
    )


def finish(rows: list[EvaluationRow], output: Path, expected_attempts: int) -> dict[str, object]:
    assert len(rows) == expected_attempts
    assert len({(r.id, r.attempt, r.stt_model) for r in rows}) == expected_attempts
    assert not any(r.submitted or r.submission_attempted for r in rows)
    assert {r.comparison_version for r in rows} == {COMPARISON_VERSION}
    summaries = {model: summarize([r for r in rows if r.stt_model == model]) for model in MODELS}
    ranking = sorted(MODELS, key=lambda model: selection_key(summaries[model]))
    for model in MODELS:
        group = [r for r in rows if r.stt_model == model]
        write_reports(summaries[model], group, model, output / "reports" / model)
    combined = {
        f"{model}.{key}": value
        for model, metrics in summaries.items()
        for key, value in metrics.items()
    }
    write_reports(combined, rows, "whisper-comparison", output / "reports")
    per_case = {
        model: {
            case: summarize([r for r in rows if r.stt_model == model and r.id == case])
            for case in sorted({r.id for r in rows})
        }
        for model in MODELS
    }
    result: dict[str, object] = {
        "comparison_version": COMPARISON_VERSION,
        "total_attempts": len(rows),
        "by_model": summaries,
        "by_case": per_case,
        "ranking": ranking,
        "selected_model": ranking[0],
        "selection_order": [
            "complete_success_rate descending",
            "field_accuracy_rate descending",
            "wer ascending",
            "average_stt_seconds ascending",
        ],
        "presentation_difference_counts": dict(
            Counter(r.stt_model for r in rows for _ in r.presentation_differences)
        ),
    }
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    lines = [
        "# Rodada 1 — Comparação dos modelos Whisper",
        "",
        f"{len(rows)} execuções completas, com tratamento rules e envio desabilitado. Comparação {COMPARISON_VERSION}.",
        "",
        "| Whisper | Acerto por campo | Sucesso completo | WER | Falhas operacionais | STT médio (s) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for model in MODELS:
        metrics = summaries[model]
        lines.append(
            f"| {model} | {metrics['field_accuracy_rate']:.2%} | {metrics['complete_success_rate']:.2%} | {metrics.get('wer', float('nan')):.2%} | {metrics['operational_failure_rate']:.2%} | {metrics.get('average_stt_seconds', 0):.2f} |"
        )
    lines += [
        "",
        f"**Modelo selecionado nesta amostra: {ranking[0]}.**",
        "Critério fixado antes da rodada: sucesso completo; acerto por campo; WER; tempo STT médio.",
        "",
        "Cada modelo foi carregado antes das medições. Os tempos STT incluem preparação e inferência, sem downloads ou carregamento inicial.",
        "Os cinco áudios e gabaritos são os mesmos para todos os modelos; cada condição tem três tentativas por formulário. As sessões do navegador são isoladas e a ordem dos modelos é alternada.",
        "Amostra de cinco gravações: a seleção descreve este corpus, sem inferir superioridade geral.",
        "",
        "## Por formulário",
        "",
        "| Whisper | Formulário | Acerto por campo | Sucesso completo | WER |",
        "| --- | --- | --- | --- | --- |",
    ]
    for model, groups in per_case.items():
        for case, metrics in groups.items():
            lines.append(
                f"| {model} | {case} | {metrics['field_accuracy_rate']:.2%} | {metrics['complete_success_rate']:.2%} | {metrics.get('wer', float('nan')):.2%} |"
            )
    lines += [
        "",
        "## Artefatos",
        "",
        "- [Protocolo](protocol.md)",
        "- [Resumo JSON](summary.json)",
        "- [Relatório HTML](reports/python-evaluation-report_whisper-comparison.html)",
        "- [Relatório CSV](reports/python-evaluation-report_whisper-comparison.csv)",
        "- [Índice de tentativas](rows.jsonl)",
        "",
        "Evidências por execução em `runs` e `evidence`. Diferenças de apresentação aceitas ficam em `presentation_differences`, sem reescrever os valores observados.",
        "",
    ]
    (output / "resumo.md").write_text("\n".join(lines))
    return result


async def compare(cases_path: Path, output: Path, attempts: int = 3) -> dict[str, object]:
    if attempts <= 0:
        raise ValueError("attempts deve ser positivo")
    cases = load_audio_cases(cases_path)
    if any(case.submitted or case.submission_authorized for case in cases):
        raise ValueError("Esta rodada requer submissão desabilitada no catálogo")
    output.mkdir(parents=True, exist_ok=True)
    model_config = load_model_config()
    if model_config.model != "deepseek-v4-flash":
        raise ValueError("A rodada requer o agente fixo deepseek-v4-flash")
    browser_config = load_browser_config()
    max_turns = load_agent_max_turns()
    settings = {
        model: TranscriptionSettings(model=model, language="pt", device="cpu", compute_type="int8")
        for model in MODELS
    }
    fingerprint = metadata(
        model=model_config, browser=browser_config, case_file=cases_path, max_turns=max_turns
    )
    audio_hashes = {
        case.id: sha256_file(case.audio_file) if case.audio_file else None for case in cases
    }
    protocol = {
        "source_sha256": fingerprint["source_sha256"],
        "catalog_sha256": fingerprint["case_file_sha256"],
        "llm": fingerprint["llm"],
        "prompt_sha256": fingerprint.get("prompt_sha256"),
        "browser": fingerprint.get("browser"),
        "max_turns": max_turns,
        "audio_sha256": audio_hashes,
        "comparison_version": COMPARISON_VERSION,
        "models": MODELS,
        "attempts_per_case_model": attempts,
        "settings": {model: config.to_dict() for model, config in settings.items()},
        "treatment": "rules",
        "data_normalization_version": DATA_NORMALIZATION_VERSION,
        "submission_authorized": False,
        "ordering": "cyclic model rotation per case/attempt",
        "selection_order": [
            "complete_success_rate descending",
            "field_accuracy_rate descending",
            "wer ascending",
            "average_stt_seconds ascending",
        ],
        "warmup_excluded_from_latency": True,
    }
    protocol_path = output / "protocol.json"
    serialized = json.dumps(protocol, ensure_ascii=False, indent=2)
    if protocol_path.exists():
        if json.loads(protocol_path.read_text()) != json.loads(serialized):
            raise ValueError("O protocolo mudou; use uma nova pasta de resultados")
    else:
        protocol_path.write_text(serialized)
    index = output / "rows.jsonl"
    rows = (
        [EvaluationRow(**json.loads(line)) for line in index.read_text().splitlines()]
        if index.exists()
        else []
    )
    finished = {(r.id, r.attempt, r.stt_model) for r in rows}
    if len(finished) != len(rows):
        raise ValueError("Tentativas duplicadas no índice de resultados")
    engines = {model: FasterWhisperSpeechToTextEngine() for model in MODELS}
    audio = {model: AudioAgent(AudioPreprocessor(), engines[model]) for model in MODELS}
    for model in MODELS:
        print(f"WARMUP {model}", flush=True)
        await asyncio.to_thread(engines[model]._get_model, settings[model])
    total = len(cases) * attempts * len(MODELS)
    for case_index, case in enumerate(cases):
        for attempt in range(1, attempts + 1):
            offset = (case_index * attempts + attempt - 1) % len(MODELS)
            order = MODELS[offset:] + MODELS[:offset]
            for position, model in enumerate(order, 1):
                if (case.id, attempt, model) in finished:
                    continue
                audio_path = case.audio_file
                if audio_path is None:
                    raise ValueError("Áudio ausente no catálogo")
                if (
                    sha256_file(cases_path) != protocol["catalog_sha256"]
                    or sha256_file(audio_path) != audio_hashes[case.id]
                ):
                    raise ValueError("O catálogo ou o áudio foi alterado durante a rodada")
                browser = (
                    replace(browser_config, url=case.form_url) if case.form_url else browser_config
                )
                app = create_application(browser_config=browser, model_config=model_config)
                app.agent.max_turns = max_turns
                try:
                    manifest = metadata(
                        model=model_config,
                        browser=browser,
                        case_file=cases_path,
                        audio_file=case.audio_file,
                        stt_settings=settings[model].to_dict(),
                        max_turns=max_turns,
                    )
                    if manifest["source_sha256"] != protocol["source_sha256"]:
                        raise ValueError("O código mudou durante a rodada")
                    manifest.update(
                        {
                            "experiment": "whisper-selection",
                            "mode": "pipeline",
                            "case_id": case.id,
                            "attempt": attempt,
                            "whisper_model": model,
                            "condition_order": list(order),
                            "execution_index": position,
                            "allow_submission": False,
                            "comparison_version": COMPARISON_VERSION,
                            "data_treatment": "rules",
                            "data_normalization_version": DATA_NORMALIZATION_VERSION,
                            "warmup_excluded_from_latency": True,
                        }
                    )
                    print(
                        f"START {len(rows) + 1}/{total} {case.id} attempt={attempt} model={model}",
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
                            audio[model],
                            settings[model],
                            trace,
                            app,
                            allow_submission=False,
                            data_treatment="rules",
                        )
                        assert not row.submitted and not row.submission_attempted
                    with index.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")
                    rows.append(row)
                    finished.add((case.id, attempt, model))
                    print(
                        f"DONE {len(rows)}/{total} {model} {row.correct}/{row.expected_count} success={row.functional_success} WER={row.wer} operational={row.operational_failure}",
                        flush=True,
                    )
                finally:
                    await app.close()
    result = finish(rows, output, total)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(compare(args.cases, args.output, args.attempts))


if __name__ == "__main__":
    main()
