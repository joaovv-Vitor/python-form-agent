from __future__ import annotations

import re
import unicodedata

from .interfaces import LanguageModel, ToolClient
from .schemas import AgentResult, FilledField, JsonObject, JsonValue, ToolCall, ToolCompletion


def submission_requested(text: str) -> bool:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", text)
        if unicodedata.category(character) != "Mn"
    ).lower()
    submit_verbs = r"(envie|enviar|submeta|submeter|mande|mandar)"
    if re.search(rf"\b(nao|nunca)\b(?:\W+\w+){{0,3}}\W+\b{submit_verbs}\b", normalized):
        return False
    return bool(re.search(rf"\b{submit_verbs}\b", normalized))


class FormAgent:
    def __init__(self, tools: ToolClient, model: LanguageModel, max_turns: int = 8) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns deve ser maior que zero")
        self.tools = tools
        self.model = model
        self.max_turns = max_turns

    async def run(self, instruction: str) -> AgentResult:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("A instrução não pode ser vazia")

        definitions = await self.tools.list_tools()
        inspection = await self.tools.inspect_form()
        allowed = {tool.name for tool in definitions}
        can_submit = submission_requested(instruction)
        session = self.model.create_session(instruction, inspection, definitions)
        filled: dict[str, JsonValue] = {}
        read: set[str] = set()
        submitted = False
        completed: list[ToolCompletion] = []
        turn_limit_reached = True

        for _ in range(self.max_turns):
            calls = await session.next(completed)
            if not calls:
                turn_limit_reached = False
                break
            completed = []
            for call in calls:
                output = await self._execute(call, allowed, can_submit)
                submitted = self._record_output(call, output, filled, read) or submitted
                completed.append(ToolCompletion(call_id=call.call_id, output=output))

        for field in list(filled):
            if field not in read:
                output = await self._safe_call("read_field", {"field": field})
                if output.get("success"):
                    filled[field] = output.get("value")

        entries = tuple(FilledField(field=field, value=value) for field, value in filled.items())
        unmatched = not entries and not submitted
        return AgentResult(
            message=self._build_message(entries, submitted, turn_limit_reached),
            inspection=inspection,
            filled=entries,
            submitted=submitted,
            unmatched=unmatched,
            turn_limit_reached=turn_limit_reached,
        )

    async def _execute(self, call: ToolCall, allowed: set[str], can_submit: bool) -> JsonObject:
        if call.name not in allowed:
            return {"success": False, "error": "Tool não permitida"}
        if call.name == "click_button" and not can_submit:
            return {"success": False, "error": "Envio bloqueado: autorização explícita necessária"}
        return await self._safe_call(call.name, call.arguments)

    async def _safe_call(self, name: str, arguments: JsonObject) -> JsonObject:
        try:
            return await self.tools.call_tool(name, arguments)
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _record_output(
        call: ToolCall,
        output: JsonObject,
        filled: dict[str, JsonValue],
        read: set[str],
    ) -> bool:
        if not output.get("success"):
            return False
        field_name = str(output.get("field") or call.arguments.get("field") or "")
        if call.name == "fill_field" and field_name:
            filled[field_name] = output.get("value")
        elif call.name == "read_field" and field_name:
            read.add(field_name)
            if field_name in filled:
                filled[field_name] = output.get("value")
        return call.name == "click_button"

    @staticmethod
    def _build_message(
        entries: tuple[FilledField, ...],
        submitted: bool,
        turn_limit_reached: bool,
    ) -> str:
        if entries:
            message = "Formulário preenchido:\n\n" + "\n".join(
                f"{entry.field}: {entry.value}" for entry in entries
            )
            if submitted:
                message += "\n\nFormulário enviado."
        elif submitted:
            message = "Formulário enviado."
        else:
            message = "Nenhum campo correspondente foi preenchido."
        if turn_limit_reached:
            message += "\n\nAviso: o limite de interações do agente foi atingido."
        return message
