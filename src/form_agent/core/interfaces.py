"""Protocols that keep orchestration independent from infrastructure."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .schemas import FormInspection, JsonObject, ToolCall, ToolCompletion, ToolDefinition


class ToolClient(Protocol):
    async def list_tools(self) -> list[ToolDefinition]: ...

    async def inspect_form(self) -> FormInspection: ...

    async def call_tool(self, name: str, arguments: JsonObject | None = None) -> JsonObject: ...

    async def close(self) -> None: ...


class SubmissionClient(ToolClient, Protocol):
    async def set_submission_authorized(self, authorized: bool) -> None: ...


class ModelSession(Protocol):
    async def next(self, completed: Sequence[ToolCompletion]) -> list[ToolCall]: ...


class LanguageModel(Protocol):
    def create_session(
        self,
        instruction: str,
        inspection: FormInspection,
        tools: Sequence[ToolDefinition],
    ) -> ModelSession: ...

    async def close(self) -> None: ...
