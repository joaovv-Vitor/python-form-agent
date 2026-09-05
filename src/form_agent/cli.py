from __future__ import annotations

import asyncio
import logging
import os

from .bootstrap import create_application
from .config import PROJECT_ROOT, load_browser_config
from .confirmation import confirm_submission
from .core.agent import submission_requested
from .core.errors import ConfigurationError, FormAgentError
from .experiments import RunTrace, metadata

LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("mcp").setLevel(max(level, logging.WARNING))


async def run_cli() -> None:
    configure_logging()
    try:
        application = create_application()
    except ConfigurationError as exc:
        print(f"Erro de configuração: {exc}")
        return

    print(
        "Form Agent Python — "
        f"perfil {application.config.profile}, modelo {application.config.model}. "
        "Digite uma instrução ou 'sair'."
    )
    try:
        while True:
            try:
                instruction = (await asyncio.to_thread(input, "Você> ")).strip()
            except EOFError:
                break
            if instruction.lower() in {"sair", "exit", "quit"}:
                break
            if instruction:
                try:
                    with RunTrace(
                        PROJECT_ROOT / "reports/runs",
                        metadata(
                            model=application.config,
                            browser=load_browser_config(),
                            max_turns=application.agent.max_turns,
                        ),
                    ) as trace:
                        application.agent.events = trace.emit
                        result = await application.agent.run(instruction)
                        print(f"Agente> {result.message}")
                        submitted = result.submitted
                        if submission_requested(instruction):
                            output = await confirm_submission(application, result)
                            trace.emit("human_submission", output)
                            submitted = submitted or output.get("submitted") is True
                            print(
                                f"Agente> {output.get('error') or ('Envio confirmado.' if output.get('submitted') else 'Envio não confirmado.')}"
                            )
                        trace.emit("run_completed", {"submitted": submitted})
                except FormAgentError as exc:
                    print(f"Agente> Não foi possível concluir a solicitação: {exc}")
                except Exception:
                    LOGGER.exception("Falha inesperada durante a execução do agente")
                    print(
                        "Agente> Ocorreu um erro inesperado. Consulte os logs para mais detalhes."
                    )

    finally:
        await application.close()


def main() -> None:
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        print("\nExecução encerrada.")


if __name__ == "__main__":
    main()
