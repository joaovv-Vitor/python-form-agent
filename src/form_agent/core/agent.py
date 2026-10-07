from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from .errors import error_code
from .events import EventSink, discard_event
from .interfaces import LanguageModel, ToolClient
from .schemas import (
    AgentResult,
    FilledField,
    FormInspection,
    JsonObject,
    JsonValue,
    RunIssue,
    ToolCall,
    ToolCompletion,
)

ALLOWED_TOOLS = frozenset({"inspect_form", "fill_field", "read_field", "click_button"})


def _normalize(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    ).lower()


def submission_denied(text: str) -> bool:
    """Conservative veto, never a source of authorization (may over-block)."""
    normalized = _normalize(text)
    return bool(
        re.search(r"\b(nao|nunca|jamais|sem)\b", normalized)
        and re.search(r"\b(envi\w*|submet\w*|submis\w*|mand\w*)\b", normalized)
    )


def submission_requested(text: str) -> bool:
    """Legacy intent hint for the UI only. This function NEVER grants permission."""
    return not submission_denied(text) and bool(
        re.search(r"\b(envie|enviar|submeta|submeter|mande|mandar)\b", _normalize(text))
    )


class FormAgent:
    def __init__(
        self,
        tools: ToolClient,
        model: LanguageModel,
        max_turns: int = 8,
        *,
        events: EventSink = discard_event,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns deve ser maior que zero")
        self.tools = tools
        self.model = model
        self.max_turns = max_turns
        self.events = events

    async def run(
        self,
        instruction: str,
        *,
        authorize_submission: bool = False,
        field_values: Mapping[str, JsonValue] | None = None,
    ) -> AgentResult:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("A instrução não pode ser vazia")
        can_submit = authorize_submission is True and not submission_denied(instruction)
        self.events(
            "form_started",
            {
                "instruction": instruction,
                "submission_authorized": can_submit,
                "validated_field_values": dict(field_values) if field_values is not None else None,
            },
        )
        definitions = [tool for tool in await self.tools.list_tools() if tool.name in ALLOWED_TOOLS]
        inspection = await self.tools.inspect_form()
        self.events("form_inspected", inspection.to_dict())
        allowed = {tool.name for tool in definitions}
        session = self.model.create_session(
            instruction,
            inspection,
            [tool for tool in definitions if can_submit or tool.name != "click_button"],
        )
        filled: dict[str, FilledField] = {}
        issues: list[RunIssue] = []
        submitted = attempted = False
        completed: list[ToolCompletion] = []
        turn_limit_reached = True
        final_inspection: FormInspection | None = None
        verification_complete = True

        for _ in range(self.max_turns):
            self.events("model_requested", {"turn": _ + 1})
            try:
                calls = await session.next(completed)
            except Exception as exc:
                self.events("model_failed", {"code": error_code(exc), "error": str(exc)})
                raise
            if not calls:
                turn_limit_reached = False
                break
            completed = []
            for call in calls:
                self.events(
                    "model_requested_tool",
                    {"call_id": call.call_id, "name": call.name, "arguments": call.arguments},
                )
                if call.name not in allowed:
                    output: JsonObject = {
                        "success": False,
                        "code": "TOOL_ERROR",
                        "error": "Tool não permitida",
                    }
                elif call.name == "fill_field" and field_values is not None:
                    if not self._permitted_fill(call, inspection, field_values):
                        output = {
                            "success": False,
                            "code": "DATA_BLOCKED",
                            "error": "Campo ou valor fora do plano validado pelo host",
                        }
                    else:
                        output = await self._safe_call(call.name, call.arguments)
                elif call.name == "click_button":
                    if not can_submit:
                        output = {
                            "success": False,
                            "code": "SUBMISSION_BLOCKED",
                            "error": "Envio bloqueado: autorização explícita externa necessária",
                        }
                    elif attempted:
                        output = {
                            "success": False,
                            "code": "SUBMISSION_BLOCKED",
                            "error": "Uma tentativa de envio já ocorreu nesta execução",
                        }
                    else:
                        verification_complete = await self._verify(filled, issues)
                        final_inspection = await self.tools.inspect_form()
                        verification_complete = (
                            self._verify_plan(final_inspection, field_values, issues)
                            and verification_complete
                        )
                        if not verification_complete:
                            output = {
                                "success": False,
                                "code": "VERIFICATION_ERROR",
                                "error": "Envio bloqueado: releitura não confirmou os valores",
                            }
                        else:
                            output = await self._safe_call(call.name, call.arguments)
                else:
                    output = await self._safe_call(call.name, call.arguments)
                attempted = attempted or output.get("submission_attempted") is True
                submitted = submitted or (
                    call.name == "click_button"
                    and output.get("submitted") is True
                    and output.get("success") is True
                )
                self.events(
                    "tool_completed", {"call_id": call.call_id, "name": call.name, "output": output}
                )
                self._record_output(call, output, filled, issues, inspection)
                completed.append(ToolCompletion(call_id=call.call_id, output=output))
                if attempted:
                    # Do not write or retry after an action whose outcome may be uncertain.
                    break
            if attempted:
                turn_limit_reached = False
                break

        if not attempted:
            verification_complete = await self._verify(filled, issues)
            try:
                final_inspection = await self.tools.inspect_form()
                verification_complete = (
                    self._verify_plan(final_inspection, field_values, issues)
                    and verification_complete
                )
            except Exception as exc:
                verification_complete = False
                issues.append(RunIssue(error_code(exc), "verification", str(exc)))
        if turn_limit_reached:
            issues.append(RunIssue("MAX_TURNS", "model", "Limite de turnos atingido"))
        entries = tuple(filled.values())
        self.events(
            "form_completed",
            {
                "submitted": submitted,
                "submission_attempted": attempted,
                "verification_complete": verification_complete,
                "error_codes": [issue.code for issue in issues],
                "final_inspection": final_inspection.to_dict() if final_inspection else None,
            },
        )
        return AgentResult(
            message=self._build_message(entries, submitted, turn_limit_reached, issues),
            inspection=inspection,
            filled=entries,
            submitted=submitted,
            unmatched=not entries and not submitted,
            turn_limit_reached=turn_limit_reached,
            final_inspection=final_inspection,
            issues=tuple(issues),
            submission_attempted=attempted,
            submission_authorized=can_submit,
            verification_complete=verification_complete,
        )

    @staticmethod
    def _permitted_fill(
        call: ToolCall, inspection: FormInspection, values: Mapping[str, JsonValue]
    ) -> bool:
        query = call.arguments.get("field")
        if not isinstance(query, str):
            return False
        matches = [
            f
            for f in inspection.fields
            if _normalize(query)
            in {_normalize(s) for s in (f.reference, f.label, f.name or "", f.id or "") if s}
        ]
        if len(matches) != 1 or matches[0].reference not in values:
            return False
        field = matches[0]
        expected = values[field.reference]
        proposed = call.arguments.get("value")
        if isinstance(expected, bool):
            return proposed == ("true" if expected else "false")
        if field.type == "select":
            return proposed == expected or any(
                o.value == expected and o.label == proposed for o in field.options
            )
        return proposed == expected

    @staticmethod
    def _verify_plan(
        inspection: FormInspection, values: Mapping[str, JsonValue] | None, issues: list[RunIssue]
    ) -> bool:
        if values is None:
            return True
        observed = {f.reference: f.value for f in inspection.fields}
        missing = [
            ref for ref, value in values.items() if ref not in observed or observed[ref] != value
        ]
        if missing:
            issues.append(
                RunIssue(
                    "EXTRACTION_APPLY_ERROR",
                    "verification",
                    "Plano validado não confirmado: " + ", ".join(missing),
                )
            )
        return not missing

    async def submit(
        self, result: AgentResult, button: str, *, authorized: bool = False
    ) -> JsonObject:
        """Host-only confirmation path; the reviewed form must still have the same state."""
        if (
            not authorized
            or result.submission_attempted
            or not result.verification_complete
            or result.turn_limit_reached
        ):
            return {"success": False, "code": "SUBMISSION_BLOCKED", "error": "Envio não autorizado"}
        current = await self.tools.inspect_form()
        if result.final_inspection is None or current != result.final_inspection:
            return {
                "success": False,
                "code": "VERIFICATION_ERROR",
                "error": "O formulário mudou desde a revisão; execute uma nova inspeção",
            }
        return await self._safe_call("click_button", {"button": button})

    async def _verify(self, filled: dict[str, FilledField], issues: list[RunIssue]) -> bool:
        verified = True
        for reference, previous in list(filled.items()):
            output = await self._safe_call("read_field", {"field": reference})
            self.events(
                "field_verified", {"field": reference, "expected": previous.value, "output": output}
            )
            if output.get("success") is not True or output.get("value") != previous.value:
                verified = False
                issues.append(
                    RunIssue(
                        "VERIFICATION_ERROR",
                        "verification",
                        f"Releitura não confirmou o campo {reference}",
                        "read_field",
                    )
                )
            if output.get("success") is True:
                filled[reference] = FilledField(previous.field, output.get("value"), reference)
        return verified

    async def _safe_call(self, name: str, arguments: JsonObject) -> JsonObject:
        self.events(f"{name}_called", {"arguments": arguments})
        try:
            output = await self.tools.call_tool(name, arguments)
        except Exception as exc:
            output = {"success": False, "code": error_code(exc), "error": str(exc)}
        self.events(f"{name}_completed", {"output": output})
        return output

    @staticmethod
    def _record_output(
        call: ToolCall,
        output: JsonObject,
        filled: dict[str, FilledField],
        issues: list[RunIssue],
        inspection: FormInspection,
    ) -> None:
        if output.get("success") is False:
            issues.append(
                RunIssue(
                    str(output.get("code") or "TOOL_ERROR"),
                    "tool",
                    str(output.get("error") or "Falha na tool"),
                    call.name,
                )
            )
            return
        label = str(output.get("field") or call.arguments.get("field") or "")
        reference = str(output.get("field_ref") or label)
        if call.name == "fill_field" and label:
            selected = next((f for f in inspection.fields if f.reference == reference), None)
            if (
                selected
                and selected.type == "radio"
                and selected.name
                and output.get("value") is True
            ):
                for sibling in inspection.fields:
                    if (
                        sibling.type == "radio"
                        and sibling.name == selected.name
                        and sibling.reference in filled
                    ):
                        previous = filled[sibling.reference]
                        filled[sibling.reference] = FilledField(
                            previous.field, False, sibling.reference
                        )
            filled[reference] = FilledField(label, output.get("value"), reference)
        # Model-requested reads do not replace the mandatory final verification.

    @staticmethod
    def _build_message(
        entries: tuple[FilledField, ...],
        submitted: bool,
        turn_limit_reached: bool,
        issues: list[RunIssue],
    ) -> str:
        if entries:
            message = "Valores observados:\n\n" + "\n".join(
                f"{e.field}: {e.value}" for e in entries
            )
        else:
            message = "Nenhum campo correspondente foi preenchido."
        if submitted:
            message += "\n\nEnvio confirmado pelo formulário."
        if turn_limit_reached:
            message += "\n\nAviso: o limite de interações do agente foi atingido."
        if issues:
            message += "\n\nOcorrências: " + ", ".join(dict.fromkeys(i.code for i in issues))
        return message
