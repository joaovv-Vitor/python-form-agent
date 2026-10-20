"""Human clarification of pending email/phone data, without another LLM or STT call."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from typing import Literal

from form_agent.core.errors import ToolClientError, error_code
from form_agent.core.events import EventSink, discard_event
from form_agent.core.interfaces import ToolClient
from form_agent.core.schemas import (
    AgentResult,
    FilledField,
    FormField,
    FormInspection,
    JsonObject,
    RunIssue,
)

from .extraction import ExtractionResult
from .normalization import FieldKind, NormalizationResult, normalize_field_value

type Ask = Callable[[str], Awaitable[str]]
type Status = Literal["resolved", "skipped", "cancelled", "exhausted", "failed"]


async def terminal_answer(question: str) -> str:
    return await asyncio.to_thread(input, question)


def field_kind(field: FormField) -> FieldKind | None:
    if field.type == "email":
        return "email"
    if field.type == "tel":
        return "phone"
    if field.type not in {"text", "search"}:
        return None
    text = " ".join((field.label, field.name or "", field.id or ""))
    text = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c)
    )
    if re.search(r"e[-_ ]?mail", text):
        return "email"
    if re.search(r"telefone|phone|celular|whatsapp", text):
        return "phone"
    return None


def _editable(field: FormField) -> bool:
    return not field.disabled and not field.readonly and field_kind(field) is not None


@dataclass(frozen=True)
class PendingQuestion:
    candidates: tuple[FormField, ...]
    reason: str
    sources: tuple[RunIssue, ...] = ()


@dataclass(frozen=True)
class ClarificationRecord:
    field: str | None
    candidates: tuple[str, ...]
    reason: str
    status: Status
    attempts: int = 0
    value: str | None = None


@dataclass(frozen=True)
class ClarificationResult:
    form: AgentResult
    issues: tuple[RunIssue, ...]
    records: tuple[ClarificationRecord, ...]


def pending_questions(
    inspection: FormInspection,
    normalization: NormalizationResult | None,
    extraction: ExtractionResult | None,
) -> list[PendingQuestion]:
    """Associate typed evidence with fields; never parse human-readable issue messages."""
    fields = tuple(f for f in inspection.fields if _editable(f))
    questions: dict[tuple[str, ...], PendingQuestion] = {}

    def add(candidates: tuple[FormField, ...], reason: str, source: RunIssue) -> None:
        if not candidates:
            return  # An unmapped source remains pending; do not guess a field.
        key = tuple(f.reference for f in candidates)
        previous = questions.get(key)
        questions[key] = PendingQuestion(
            candidates,
            f"{previous.reason} {reason}" if previous and reason != previous.reason else reason,
            (*previous.sources, source) if previous else (source,),
        )

    if normalization:
        pending = [f for f in normalization.fields if f.status == "pending"]
        for item, source in zip(pending, normalization.issues, strict=True):
            add(
                tuple(f for f in fields if field_kind(f) == item.kind),
                item.reason or "Informação incerta.",
                source,
            )
    if extraction:
        pending_extracted = [f for f in extraction.fields if f.status == "pending"]
        for extracted, source in zip(pending_extracted, extraction.issues, strict=True):
            add(
                tuple(f for f in fields if f.reference == extracted.field),
                extracted.reason or "Informação incerta.",
                source,
            )
    return list(questions.values())


class ClarificationSession:
    def __init__(
        self,
        ask: Ask = terminal_answer,
        *,
        notify: Callable[[str], None] = print,
        max_attempts: int = 2,
        events: EventSink = discard_event,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("O limite de tentativas deve ser positivo.")
        self.ask = ask
        self.notify = notify
        self.max_attempts = max_attempts
        self.events = events

    async def _answer(self, question: str) -> str:
        try:
            return (await self.ask(question)).strip()
        except EOFError:
            return "ENCERRAR"

    async def _resolve(
        self,
        task: PendingQuestion,
        tools: ToolClient,
        expected: FormInspection,
    ) -> tuple[ClarificationRecord, FormInspection]:
        candidates = tuple(f.reference for f in task.candidates)
        field = task.candidates[0]
        if len(candidates) > 1:
            options = "\n".join(
                f"{i}. {f.label} [{f.reference}]" for i, f in enumerate(task.candidates, 1)
            )
            for _ in range(self.max_attempts):
                question = (
                    f"{task.reason}\nA qual campo essa informação se refere?\n{options}\n"
                    "Digite o número ou identificador, PULAR ou ENCERRAR: "
                )
                self.events(
                    "clarification_question", {"candidates": candidates, "question": question}
                )
                answer = await self._answer(question)
                self.events("clarification_answer", {"candidates": candidates, "answer": answer})
                if answer.upper() in {"PULAR", "ENCERRAR"}:
                    return (
                        ClarificationRecord(
                            None,
                            candidates,
                            task.reason,
                            "skipped" if answer.upper() == "PULAR" else "cancelled",
                        ),
                        expected,
                    )
                selected = [
                    f for i, f in enumerate(task.candidates, 1) if answer in {str(i), f.reference}
                ]
                if len(selected) == 1:
                    field = selected[0]
                    break
                self.notify("Escolha um dos campos apresentados.")
            else:
                return ClarificationRecord(None, candidates, task.reason, "exhausted"), expected

        kind = field_kind(field)
        assert kind is not None
        detail = "o e-mail completo" if kind == "email" else "o telefone completo, incluindo o DDD"
        for attempt in range(1, self.max_attempts + 1):
            question = (
                f"{field.label}: {task.reason}\nInforme {detail} ou digite PULAR ou ENCERRAR: "
            )
            self.events("clarification_question", {"field": field.reference, "question": question})
            answer = await self._answer(question)
            self.events("clarification_answer", {"field": field.reference, "answer": answer})
            if answer.upper() in {"PULAR", "ENCERRAR"}:
                return (
                    ClarificationRecord(
                        field.reference,
                        candidates,
                        task.reason,
                        "skipped" if answer.upper() == "PULAR" else "cancelled",
                        attempt,
                    ),
                    expected,
                )
            value, _, reason = normalize_field_value(kind, answer)
            if reason or value is None:
                self.notify(reason or "Informe um valor completo.")
                continue
            # Detect changes while waiting for the user; never write into a stale form.
            before = await tools.inspect_form()
            current = [f for f in before.fields if f.reference == field.reference]
            if before != expected or len(current) != 1 or current[0] != field:
                raise ToolClientError(
                    "O campo mudou durante o esclarecimento.", "VERIFICATION_ERROR"
                )
            arguments: JsonObject = {"field": field.reference, "value": value}
            self.events("fill_field_called", {"arguments": arguments})
            output = await tools.call_tool("fill_field", arguments)
            self.events("fill_field_completed", {"output": output})
            if output.get("success") is not True:
                raise ToolClientError(
                    str(output.get("error") or "Não foi possível aplicar a resposta."),
                    str(output.get("code") or "TOOL_ERROR"),
                )
            after = await tools.inspect_form()
            other_before = tuple(
                (f.reference, f.value) for f in before.fields if f.reference != field.reference
            )
            other_after = tuple(
                (f.reference, f.value) for f in after.fields if f.reference != field.reference
            )
            actual = [f for f in after.fields if f.reference == field.reference]
            if (
                after.url != before.url
                or other_before != other_after
                or len(actual) != 1
                or actual[0].value != value
            ):
                raise ToolClientError(
                    "O formulário divergiu após a resposta.", "VERIFICATION_ERROR"
                )
            field = actual[0]
            expected = after
            self.events(
                "field_verified", {"field": field.reference, "expected": value, "output": output}
            )
            if field.valid is False:
                self.notify(field.validation_message or "O formulário não aceitou esse valor.")
                continue
            self.notify(f"{field.label}: preenchido e conferido.")
            return (
                ClarificationRecord(
                    field.reference, candidates, task.reason, "resolved", attempt, value
                ),
                expected,
            )
        return (
            ClarificationRecord(
                field.reference, candidates, task.reason, "exhausted", self.max_attempts
            ),
            expected,
        )

    async def run(
        self,
        tools: ToolClient,
        form: AgentResult,
        issues: tuple[RunIssue, ...],
        *,
        normalization: NormalizationResult | None = None,
        extraction: ExtractionResult | None = None,
    ) -> ClarificationResult:
        # Data clarification cannot repair an uncertain browser state or a past submission.
        if (
            not form.verification_complete
            or form.final_inspection is None
            or form.submission_attempted
            or form.submitted
            or form.turn_limit_reached
        ):
            return ClarificationResult(form, issues, ())
        inspection = form.final_inspection
        active = list(issues)
        records: list[ClarificationRecord] = []
        written = {f.reference: f for f in form.filled}
        tasks = pending_questions(inspection, normalization, extraction)
        handled: set[str] = set()
        form_issues = list(form.issues)
        verified: bool = True
        cancelled = False
        while True:
            if not tasks:
                # Also find omitted/invalid fields, including candidates not chosen above.
                tasks = [
                    PendingQuestion(
                        (f,),
                        "Campo obrigatório não informado."
                        if not f.value
                        else "Valor inválido no formulário.",
                    )
                    for f in inspection.fields
                    if _editable(f)
                    and f.reference not in handled
                    and ((f.required and not f.value) or f.valid is False)
                ]
                if not tasks:
                    break
            task = tasks.pop(0)
            pending_issue = RunIssue(
                "DATA_PENDING",
                "clarification",
                f"{', '.join(f.reference for f in task.candidates)}: {task.reason}",
            )
            if not task.sources:
                active.append(pending_issue)
            try:
                current = await tools.inspect_form()
                if current != inspection:
                    raise ToolClientError(
                        "O formulário mudou desde a revisão.", "VERIFICATION_ERROR"
                    )
                record, expected = await self._resolve(task, tools, inspection)
                inspection = await tools.inspect_form()
                if inspection != expected:
                    raise ToolClientError(
                        "O formulário mudou após o esclarecimento.", "VERIFICATION_ERROR"
                    )
            except Exception as exc:
                record = ClarificationRecord(
                    task.candidates[0].reference if len(task.candidates) == 1 else None,
                    tuple(f.reference for f in task.candidates),
                    task.reason,
                    "failed",
                )
                issue = RunIssue(error_code(exc), "clarification", str(exc))
                active.append(issue)
                form_issues.append(issue)
                verified = False
                try:
                    inspection = await tools.inspect_form()
                except Exception:
                    pass  # Keep the last observed snapshot and mark it unverified.
                self.notify(f"Não foi possível concluir o esclarecimento: {exc}")
            records.append(record)
            self.events("clarification_record", asdict(record))
            if record.field:
                handled.add(record.field)
            else:
                handled.update(record.candidates)
            if record.status == "resolved":
                resolved_sources = task.sources or (pending_issue,)
                active = [issue for issue in active if issue not in resolved_sources]
                updated = next(f for f in inspection.fields if f.reference == record.field)
                written[updated.reference] = FilledField(
                    updated.label, updated.value, updated.reference
                )
            if record.status in {"cancelled", "failed"}:
                cancelled = True
                break

        # Cancellation must not hide mandatory fields that had not yet been asked about.
        if (
            cancelled
            and any(
                _editable(f) and ((f.required and not f.value) or f.valid is False)
                for f in inspection.fields
            )
            and not any(i.code == "DATA_PENDING" for i in active)
        ):
            active.append(
                RunIssue("DATA_PENDING", "clarification", "Há campos pendentes no formulário.")
            )
        entries = tuple(written.values())
        message = (
            "Valores observados:\n\n" + "\n".join(f"{f.field}: {f.value}" for f in entries)
            if entries
            else form.message
        )
        if active:
            message += "\n\nOcorrências: " + ", ".join(dict.fromkeys(i.code for i in active))
        updated_form = replace(
            form,
            filled=entries,
            final_inspection=inspection,
            issues=tuple(form_issues),
            verification_complete=verified,
            unmatched=not entries and not form.submitted,
            message=message,
        )
        self.events(
            "clarification_completed",
            {
                "records": [asdict(r) for r in records],
                "final_inspection": inspection.to_dict(),
                "verification_complete": verified,
                "submitted": form.submitted,
            },
        )
        return ClarificationResult(updated_form, tuple(active), tuple(records))
