"""Application-specific exceptions exposed to entry points."""

from __future__ import annotations


class FormAgentError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(FormAgentError):
    """Raised when local configuration is missing or invalid."""


class ModelError(FormAgentError):
    """Base class for language-model failures."""


class ModelAuthenticationError(ModelError):
    """Raised when the configured model credentials are rejected."""


class ModelTimeoutError(ModelError):
    """Raised when the model does not respond before the configured timeout."""


class ModelCommunicationError(ModelError):
    """Raised when the model provider cannot be reached or rejects a request."""


class ModelResponseError(ModelError):
    """Raised when the model returns an unusable response."""


class ToolClientError(FormAgentError):
    """Raised when the MCP tool client cannot complete an operation."""

    def __init__(self, message: str, code: str = "TOOL_ERROR") -> None:
        super().__init__(message)
        self.code = code


class BrowserControllerError(FormAgentError):
    """Base class for browser automation failures."""


class ElementNotFoundError(BrowserControllerError):
    """Raised when no form element matches a semantic query."""


class AmbiguousElementError(BrowserControllerError):
    """Raised when a semantic query matches more than one element."""


def error_code(error: Exception) -> str:
    if isinstance(error, ToolClientError):
        return error.code
    if isinstance(error, ElementNotFoundError):
        return "FIELD_NOT_FOUND"
    if isinstance(error, AmbiguousElementError):
        return "FIELD_AMBIGUOUS"
    if isinstance(error, BrowserControllerError):
        return "BROWSER_ERROR"
    if isinstance(error, ModelError):
        return "PROVIDER_ERROR"
    if isinstance(error, TimeoutError):
        return "TIMEOUT"
    return "TOOL_ERROR"
