from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .mcp_client import BrowserToolsClient
from .model import OpenAICompatibleModel


@dataclass
class AgentResult:
    message: str
    inspection: dict[str, Any]
    filled: list[dict[str, Any]]
    submitted: bool
    unmatched: bool


def submission_requested(text: str) -> bool:
    normalized = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower()
    if re.search(r"\b(nao|nunca)\s+(envie|enviar|submeta|submeter|mande|mandar)\b", normalized):
        return False
    return bool(re.search(r"\b(envie|enviar|submeta|submeter|mande|mandar)\b", normalized))


class FormAgent:
    def __init__(self, mcp: BrowserToolsClient, model: OpenAICompatibleModel, max_turns: int = 8) -> None:
        self.mcp, self.model, self.max_turns = mcp, model, max_turns

    async def run(self, instruction: str) -> AgentResult:
        tools = await self.mcp.list_tools()
        inspection = await self.mcp.call_tool("inspect_form")
        allowed = {tool["name"] for tool in tools}
        can_submit = submission_requested(instruction)
        session = self.model.create_session(instruction, inspection, tools)
        filled: dict[str, Any] = {}
        read: set[str] = set()
        submitted, completed = False, []
        for _ in range(self.max_turns):
            calls = await session.next(completed)
            if not calls:
                break
            completed = []
            for call in calls:
                try:
                    if call["name"] not in allowed:
                        output = {"success": False, "error": "Tool não permitida"}
                    elif call["name"] == "click_button" and not can_submit:
                        output = {"success": False, "error": "Envio bloqueado: autorização explícita necessária"}
                    else:
                        output = await self.mcp.call_tool(call["name"], call["arguments"])
                        if call["name"] == "fill_field" and output.get("success"):
                            filled[str(output.get("field", call["arguments"].get("field")))] = output.get("value")
                        if call["name"] == "read_field" and output.get("success"):
                            field = str(output.get("field", call["arguments"].get("field")))
                            read.add(field)
                            if field in filled:
                                filled[field] = output.get("value")
                        if call["name"] == "click_button" and output.get("success"):
                            submitted = True
                except Exception as exc:
                    output = {"success": False, "error": str(exc)}
                completed.append({"call_id": call["call_id"], "output": output})
        for field in list(filled):
            if field not in read:
                filled[field] = (await self.mcp.call_tool("read_field", {"field": field})).get("value")
        entries = [{"field": field, "value": value} for field, value in filled.items()]
        unmatched = not entries and not submitted
        message = "Formulário preenchido:\n\n" + "\n".join(f'{e["field"]}: {e["value"]}' for e in entries) if entries else "Formulário enviado." if submitted else "Nenhum campo correspondente foi preenchido."
        if entries and submitted:
            message += "\n\nFormulário enviado."
        return AgentResult(message, inspection, entries, submitted, unmatched)
