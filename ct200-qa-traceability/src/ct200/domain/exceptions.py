"""Domain-specific exception hierarchy for the CT200 QA Traceability System."""

from typing import Any


class CT200Error(Exception):
    """Base exception for all domain errors.

    Attributes:
        message: Human-readable error description.
        code: Machine-readable error code (e.g., AUTH_REQUIRED).
        status_code: HTTP status code to return.
        details: Optional additional context.
    """

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str = "An internal error occurred",
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or {}


class ValidationError(CT200Error):
    """Input validation failures (422)."""

    code = "VALIDATION_ERROR"
    status_code = 422


class NotFoundError(CT200Error):
    """Requested resource does not exist (404)."""

    code = "RESOURCE_NOT_FOUND"
    status_code = 404


class ConflictError(CT200Error):
    """Operation conflicts with current state (409)."""

    code = "CONFLICT"
    status_code = 409


class ParsingError(CT200Error):
    """PDF parsing failures (422)."""

    code = "PARSING_ERROR"
    status_code = 422


class FileTooLargeError(CT200Error):
    """Uploaded file exceeds size limit (413)."""

    code = "FILE_TOO_LARGE"
    status_code = 413


class InvalidFileFormatError(CT200Error):
    """File fails magic-byte validation (422)."""

    code = "INVALID_FILE_FORMAT"
    status_code = 422


class PathologicalInputError(CT200Error):
    """Input contains pathological content (422)."""

    code = "PATHOLOGICAL_INPUT"
    status_code = 422


class TreeValidationError(CT200Error):
    """Tree construction or validation failures (422)."""

    code = "TREE_VALIDATION_FAILED"
    status_code = 422


class TimeoutError(CT200Error):
    """Operation exceeded configured wall-clock timeout (504)."""

    code = "TIMEOUT"
    status_code = 504


class GenerationError(CT200Error):
    """QA generation failures — LLM unreachable or schema invalid (502)."""

    code = "GENERATION_ERROR"
    status_code = 502


class GenerationTimeoutError(CT200Error):
    """Generation request exceeded hard timeout (504)."""

    code = "GENERATION_TIMEOUT"
    status_code = 504


class AuthenticationError(CT200Error):
    """Missing or invalid authentication credentials (401)."""

    code = "AUTH_REQUIRED"
    status_code = 401


class RateLimitError(CT200Error):
    """Client exceeded configured rate limit (429)."""

    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429


class PersistenceError(CT200Error):
    """Database constraint violation or connection failure (500)."""

    code = "PERSISTENCE_ERROR"
    status_code = 500


class ServiceUnavailableError(CT200Error):
    """Service dependency unavailable (503)."""

    code = "SERVICE_UNAVAILABLE"
    status_code = 503
