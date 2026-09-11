"""Typed domain exceptions for DeskForge."""

from __future__ import annotations


class DeskForgeError(Exception):
    """Base exception for all DeskForge errors."""


class ValidationError(DeskForgeError):
    """Raised when user input or application configuration is invalid."""


class AppNotFoundError(DeskForgeError):
    """Raised when a managed application cannot be located by ID or name."""


class AppAlreadyExistsError(DeskForgeError):
    """Raised when attempting to create a duplicate managed application."""


class InspectionError(DeskForgeError):
    """Raised when target inspection fails unexpectedly."""


class DesktopEntryError(DeskForgeError):
    """Raised when generating, parsing, or validating a .desktop file fails."""


class SystemIntegrationError(DeskForgeError):
    """Raised when an OS-level integration action fails."""
