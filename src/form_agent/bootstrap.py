"""Compose the application dependencies used by the command entry points."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .adapters.mcp_client import BrowserToolsClient
from .adapters.openai_model import OpenAICompatibleModel
from .config import ModelConfig, load_agent_max_turns, load_model_config
from .core.agent import FormAgent


@dataclass(slots=True)
class Application:
    """Runtime dependencies shared by the CLI and evaluation runner."""

    config: ModelConfig
    agent: FormAgent
    client: BrowserToolsClient
    model: OpenAICompatibleModel

    async def close(self) -> None:
        """Release all external resources without masking evaluation results."""
        for resource in (self.model, self.client):
            try:
                await resource.close()
            except asyncio.CancelledError:
                continue
            except Exception:
                continue


def create_application() -> Application:
    config = load_model_config()
    client = BrowserToolsClient()
    model = OpenAICompatibleModel(config)
    agent = FormAgent(client, model, max_turns=load_agent_max_turns())
    return Application(config=config, agent=agent, client=client, model=model)
