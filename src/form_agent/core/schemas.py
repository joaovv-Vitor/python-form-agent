"""Typed values exchanged between the application components."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class FormOption:
    label: str
    value: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FormOption:
        return cls(label=str(value.get("label", "")), value=str(value.get("value", "")))

    def to_dict(self) -> JsonObject:
        return {"label": self.label, "value": self.value}


@dataclass(frozen=True, slots=True)
class FormField:
    label: str
    name: str | None
    id: str | None
    type: str
    role: str
    placeholder: str | None = None
    required: bool = False
    disabled: bool = False
    options: tuple[FormOption, ...] = ()
    value: JsonValue = None
    valid: bool | None = None
    validation_message: str = ""
    readonly: bool = False

    @property
    def reference(self) -> str:
        return self.id or self.name or self.label

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FormField:
        raw_options = value.get("options", [])
        options = tuple(
            FormOption.from_mapping(item) for item in raw_options if isinstance(item, Mapping)
        )
        return cls(
            label=str(value.get("label", "")),
            name=str(value["name"]) if value.get("name") is not None else None,
            id=str(value["id"]) if value.get("id") is not None else None,
            type=str(value.get("type", "text")),
            role=str(value.get("role", "textbox")),
            placeholder=str(value["placeholder"]) if value.get("placeholder") is not None else None,
            required=bool(value.get("required", False)),
            disabled=bool(value.get("disabled", False)),
            options=options,
            value=value.get("value"),
            valid=value.get("valid"),
            validation_message=str(value.get("validation_message") or ""),
            readonly=bool(value.get("readonly", False)),
        )

    def to_dict(self) -> JsonObject:
        result: JsonObject = {
            "label": self.label,
            "name": self.name,
            "id": self.id,
            "type": self.type,
            "role": self.role,
            "placeholder": self.placeholder,
            "required": self.required,
            "disabled": self.disabled,
            "value": self.value,
            "valid": self.valid,
            "validation_message": self.validation_message,
            "readonly": self.readonly,
        }
        if self.options:
            result["options"] = [option.to_dict() for option in self.options]
        return result


@dataclass(frozen=True, slots=True)
class FormButton:
    label: str
    name: str | None
    id: str | None
    type: str = "button"
    role: str = "button"
    disabled: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FormButton:
        return cls(
            label=str(value.get("label", "")),
            name=str(value["name"]) if value.get("name") is not None else None,
            id=str(value["id"]) if value.get("id") is not None else None,
            type=str(value.get("type", "button")),
            role=str(value.get("role", "button")),
            disabled=bool(value.get("disabled", False)),
        )

    def to_dict(self) -> JsonObject:
        return {
            "label": self.label,
            "name": self.name,
            "id": self.id,
            "type": self.type,
            "role": self.role,
            "disabled": self.disabled,
        }


@dataclass(frozen=True, slots=True)
class FormInspection:
    url: str
    fields: tuple[FormField, ...] = ()
    buttons: tuple[FormButton, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FormInspection:
        raw_fields = value.get("fields", [])
        raw_buttons = value.get("buttons", [])
        return cls(
            url=str(value.get("url", "")),
            fields=tuple(
                FormField.from_mapping(item) for item in raw_fields if isinstance(item, Mapping)
            ),
            buttons=tuple(
                FormButton.from_mapping(item) for item in raw_buttons if isinstance(item, Mapping)
            ),
        )

    def to_dict(self) -> JsonObject:
        return {
            "url": self.url,
            "fields": [item.to_dict() for item in self.fields],
            "buttons": [item.to_dict() for item in self.buttons],
        }


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: JsonObject = field(default_factory=dict)

    def to_api_dict(self) -> JsonObject:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCompletion:
    call_id: str
    output: JsonObject


@dataclass(frozen=True, slots=True)
class FilledField:
    field: str
    value: JsonValue
    reference: str = ""


@dataclass(frozen=True, slots=True)
class RunIssue:
    code: str
    stage: str
    message: str
    tool: str | None = None


@dataclass(frozen=True, slots=True)
class AgentResult:
    message: str
    inspection: FormInspection
    filled: tuple[FilledField, ...]
    submitted: bool
    unmatched: bool
    turn_limit_reached: bool = False
    final_inspection: FormInspection | None = None
    issues: tuple[RunIssue, ...] = ()
    submission_attempted: bool = False
    submission_authorized: bool = False
    verification_complete: bool = True
