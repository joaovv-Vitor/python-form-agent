from __future__ import annotations

import asyncio

from .agent import FormAgent
from .config import load_model_config
from .mcp_client import BrowserToolsClient
from .model import OpenAICompatibleModel


async def run_cli() -> None:
    config = load_model_config()
    client = BrowserToolsClient()
    agent = FormAgent(client, OpenAICompatibleModel(config))
    print(f"Form Agent Python — perfil {config.profile}, modelo {config.model}. Digite uma instrução ou 'sair'.")
    try:
        while True:
            instruction = (await asyncio.to_thread(input, "Você> ")).strip()
            if instruction.lower() in {"sair", "exit", "quit"}:
                break
            if instruction:
                print(f"Agente> {(await agent.run(instruction)).message}")
    finally:
        await client.close()


def main() -> None:
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
