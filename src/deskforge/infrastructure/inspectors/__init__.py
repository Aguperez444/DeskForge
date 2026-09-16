"""Smart target inspectors (Strategy Pattern) and Java runtime discovery."""

from deskforge.infrastructure.inspectors.base import BaseInspector, guess_name_and_version
from deskforge.infrastructure.inspectors.java_runtime import detect_java_runtimes
from deskforge.infrastructure.inspectors.registry import InspectorRegistry

__all__ = [
    "BaseInspector",
    "InspectorRegistry",
    "detect_java_runtimes",
    "guess_name_and_version",
]
