"""
Application-specific exception hierarchy.

Centralizing exceptions here lets the UI layer catch narrow, meaningful
error types (see FUNCTION 12 - ERROR HANDLING in the spec) instead of
bare `Exception`, and lets every layer raise errors with a consistent,
loggable shape.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all application-raised errors."""


class ConfigurationError(AppError):
    """Raised when required configuration/environment values are missing or invalid."""


class NetworkUnavailableError(AppError):
    """Raised when the machine has no working internet connection."""


class WebsiteTimeoutError(AppError):
    """Raised when a remote site does not respond within the configured timeout."""


class WebsiteStructureChangedError(AppError):
    """Raised when expected page elements/selectors are not found.

    This typically means the target website's markup changed and the
    scraper's selectors need to be updated.
    """


class LoginFailedError(AppError):
    """Raised when authentication against a remote portal (e.g. ECRI) fails."""


class SessionExpiredError(AppError):
    """Raised when an authenticated session has expired mid-operation."""


class DuplicateRecallError(AppError):
    """Raised when attempting to insert a recall record that already exists."""


class InvalidExcelFileError(AppError):
    """Raised when an uploaded Excel file cannot be parsed at all."""


class MissingColumnsError(AppError):
    """Raised when required inventory columns cannot be located or mapped."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Missing required inventory columns: {', '.join(missing)}")


class DatabaseError(AppError):
    """Raised for unexpected SQLite errors."""


class CredentialError(AppError):
    """Raised when secure credential storage/retrieval fails."""


class ReportGenerationError(AppError):
    """Raised when Excel/PDF report generation fails."""
