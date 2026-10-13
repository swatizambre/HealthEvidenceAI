"""Application errors returned as structured API responses."""

from __future__ import annotations


class AppError(Exception):
    """Safe error that can be shown to an API client."""

    def __init__(self, error_code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


class NotFoundError(AppError):
    """A requested synthetic record does not exist."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(error_code, message, 404)


class LLMUnavailable(AppError):
    """The configured language-model provider cannot be called."""

    def __init__(self, message: str = "The language model provider is unavailable.") -> None:
        super().__init__("LLM_UNAVAILABLE", message, 503)


class RetrievalError(AppError):
    """Chunk retrieval failed before an answer could be formed."""

    def __init__(self, message: str = "Evidence retrieval failed.") -> None:
        super().__init__("RETRIEVAL_FAILED", message, 503)
