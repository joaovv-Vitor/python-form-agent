"""HTTP commands never accept local file paths or browser destinations."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)


class SubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal["ENVIAR"]
    revision: int = Field(ge=0)
