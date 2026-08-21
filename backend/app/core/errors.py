"""Application error types and their HTTP representation.

Every failure the API can produce is one of these. Routes raise them; a single
exception handler in ``app.main`` renders them. No route builds an error body
by hand.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-facing application errors."""

    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class InvalidRepositoryUrlError(AppError):
    status_code = 422
    code = "INVALID_REPOSITORY_URL"


class RepositoryNotFoundError(AppError):
    status_code = 404
    code = "REPOSITORY_NOT_FOUND"


class DocumentationProviderNotConfiguredError(AppError):
    """Raised when generation is requested but no CodeWiki provider is wired.

    This is the honest failure for the current phase: CodeOops orchestrates a
    documentation engine, and no engine is connected yet.
    """

    status_code = 501
    code = "DOCUMENTATION_PROVIDER_NOT_CONFIGURED"


class JobNotFoundError(AppError):
    status_code = 404
    code = "JOB_NOT_FOUND"


class DocumentationNotAvailableError(AppError):
    """Raised when a job's documentation is requested but isn't there yet.

    Carries the job's real failure code/message in ``details`` — the response
    body never contains a substitute document.
    """

    status_code = 409
    code = "DOCUMENTATION_NOT_AVAILABLE"


class InvalidArchiveError(AppError):
    """The uploaded file is not a well-formed ZIP archive."""

    status_code = 422
    code = "INVALID_ARCHIVE"


class UnsafeArchiveError(AppError):
    """The archive contains an entry that could escape its extraction directory."""

    status_code = 422
    code = "UNSAFE_ARCHIVE"


class ArchiveTooLargeError(AppError):
    """The archive (compressed, extracted, or its file count) exceeds a configured limit."""

    status_code = 413
    code = "ARCHIVE_TOO_LARGE"


class EmptyRepositoryError(AppError):
    """The archive contains no files CodeWiki could analyze."""

    status_code = 422
    code = "EMPTY_REPOSITORY"
