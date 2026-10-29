"""Validated HTTP commands; browser destinations are HTTP(S) URLs or catalogue entries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from form_agent.core.schemas import JsonObject


class SessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(default="", max_length=2048)


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class SubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["ENVIAR"]
    revision: int = Field(ge=0)


class ExtensionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    document_id: str = Field(min_length=1, max_length=128)


class ExtensionReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=64)
    result: JsonObject
