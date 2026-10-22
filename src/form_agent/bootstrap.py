"""Compose the application dependencies used by the command entry points."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .adapters.mcp_client import BrowserToolsClient
from .adapters.openai_model import OpenAICompatibleModel
from .config import (
    BrowserConfig,
    ModelConfig,
    load_agent_max_turns,
    load_browser_config,
    load_model_config,
)
from .core.agent import FormAgent
from .core.events import EventSink, discard_event


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


def create_application(
    *, events: EventSink = discard_event, browser_config: BrowserConfig | None = None,
    model_config: ModelConfig | None = None,
) -> Application:
    config = model_config or load_model_config()
    client = BrowserToolsClient(browser_config=browser_config or load_browser_config())
    model = OpenAICompatibleModel(config)
    agent = FormAgent(client, model, max_turns=load_agent_max_turns(), events=events)
    return Application(config=config, agent=agent, client=client, model=model)
