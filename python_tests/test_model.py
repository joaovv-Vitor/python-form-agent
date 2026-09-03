from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError

from python_poc.config import ModelConfig
from python_poc.errors import ModelAuthenticationError, ModelResponseError
from python_poc.model import OpenAIModelSession
from python_poc.schemas import FormInspection, ToolDefinition


def session_with(completions):
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAIModelSession(
        client,
        ModelConfig("test", "test", "test-model", "test-key"),
        "Preencha o nome",
        FormInspection("file:///form.html"),
        [ToolDefinition("fill_field", "fill", {"type": "object"})],
    )


@pytest.mark.asyncio
async def test_translates_authentication_error():
    class Completions:
        async def create(self, **kwargs):
            request = httpx.Request("POST", "https://provider.example/chat")
            response = httpx.Response(401, request=request)
            raise AuthenticationError("invalid key", response=response, body={})

    with pytest.raises(ModelAuthenticationError, match="chave da API"):
        await session_with(Completions()).next([])


@pytest.mark.asyncio
async def test_rejects_invalid_tool_arguments():
    function = SimpleNamespace(name="fill_field", arguments="not-json")
    tool_call = SimpleNamespace(type="function", id="call-1", function=function)
    message = SimpleNamespace(tool_calls=[tool_call], model_dump=lambda **kwargs: {})
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class Completions:
        async def create(self, **kwargs):
            return response

    with pytest.raises(ModelResponseError, match="JSON inválidos"):
        await session_with(Completions()).next([])
