from __future__ import annotations

import asyncio
import logging
import os

from .bootstrap import create_application
from .core.errors import ConfigurationError, FormAgentError

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
                    result = await application.agent.run(instruction)
                except FormAgentError as exc:
                    print(f"Agente> Não foi possível concluir a solicitação: {exc}")
                except Exception:
                    LOGGER.exception("Falha inesperada durante a execução do agente")
                    print(
                        "Agente> Ocorreu um erro inesperado. Consulte os logs para mais detalhes."
                    )
                else:
                    print(f"Agente> {result.message}")
    finally:
        await application.close()


def main() -> None:
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        print("\nExecução encerrada.")


if __name__ == "__main__":
    main()
