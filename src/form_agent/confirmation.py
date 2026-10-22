"""Explicit human authorization after displaying and verifying the form."""

from __future__ import annotations

import asyncio

from .bootstrap import Application
from .core.schemas import AgentResult, JsonObject


async def submit_confirmed(application: Application, result: AgentResult) -> JsonObject:
    """Host-only operation shared by the CLI and an explicitly confirmed web request."""
    inspection = result.final_inspection
    buttons = (
        [b for b in inspection.buttons if b.type == "submit" and not b.disabled]
        if inspection
        else []
    )
    if len(buttons) != 1 or not result.verification_complete or result.turn_limit_reached:
        return {
            "success": False,
            "code": "SUBMISSION_BLOCKED",
            "error": "Revisão incompleta ou botão ambíguo",
        }
    await application.client.set_submission_authorized(True)
    try:
        return await application.agent.submit(
            result, buttons[0].id or buttons[0].label, authorized=True
        )
    finally:
        await application.client.set_submission_authorized(False)


async def confirm_submission(application: Application, result: AgentResult) -> JsonObject:
    inspection = result.final_inspection or result.inspection
    buttons = [
        button for button in inspection.buttons if button.type == "submit" and not button.disabled
    ]
    if len(buttons) != 1 or not result.verification_complete or result.turn_limit_reached:
        return {
            "success": False,
            "code": "SUBMISSION_BLOCKED",
            "error": "Revisão incompleta ou botão ambíguo",
        }
    print("Revisão para envio:")
    for field in inspection.fields:
        status = f" — {field.validation_message}" if field.valid is False else ""
        print(f"  {field.label}: {field.value}{status}")
    try:
        answer = await asyncio.to_thread(
            input, "Revise os valores acima. Digite ENVIAR para autorizar esta submissão: "
        )
    except EOFError:
        answer = ""
    if answer.strip() != "ENVIAR":
        return {"success": False, "code": "SUBMISSION_BLOCKED", "error": "Envio não confirmado"}
    return await submit_confirmed(application, result)
