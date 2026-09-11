"""Atomic JSON repository for DeskForge managed applications."""

from __future__ import annotations

import json
import os
from pathlib import Path

from deskforge.domain.exceptions import AppNotFoundError
from deskforge.domain.models import ManagedApp


class AppRepository:
    """Manages persistent storage of ManagedApp entities in registry.json."""

    SCHEMA_VERSION = 1

    def __init__(self, registry_file: Path) -> None:
        self._registry_file = registry_file

    def _read_all(self) -> list[ManagedApp]:
        if not self._registry_file.exists():
            return []
        try:
            data = json.loads(self._registry_file.read_text(encoding="utf-8"))
            items = data.get("apps", []) if isinstance(data, dict) else []
            return [ManagedApp.from_dict(item) for item in items if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            return []

    def _write_all(self, apps: list[ManagedApp]) -> None:
        self._registry_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._registry_file.with_suffix(".json.tmp")
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "apps": [app.to_dict() for app in apps],
        }
        tmp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, self._registry_file)

    def list_all(self) -> list[ManagedApp]:
        apps = self._read_all()
        return sorted(apps, key=lambda a: a.name.lower())

    def get(self, app_id: str) -> ManagedApp | None:
        for app in self._read_all():
            if app.id == app_id:
                return app
        return None

    def find_by_id_or_name(self, query: str) -> ManagedApp:
        """Find an app by exact ID, exact name (case-insensitive), or unique ID prefix."""
        apps = self._read_all()
        q = query.strip()
        q_lower = q.lower()

        for app in apps:
            if app.id == q:
                return app
        for app in apps:
            if app.name.lower() == q_lower:
                return app

        prefix_matches = [app for app in apps if app.id.startswith(q) or app.name.lower().startswith(q_lower)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]

        raise AppNotFoundError(f"No se encontró ninguna aplicación con identificador o nombre '{query}'.")

    def find_by_target(self, target_path: str) -> ManagedApp | None:
        resolved = str(Path(target_path).expanduser()) if not target_path.startswith(("http://", "https://")) else target_path
        for app in self._read_all():
            if app.exec_target == resolved or app.exec_target == target_path:
                return app
        return None

    def upsert(self, app: ManagedApp) -> ManagedApp:
        apps = self._read_all()
        replaced = False
        for idx, existing in enumerate(apps):
            if existing.id == app.id:
                apps[idx] = app
                replaced = True
                break
        if not replaced:
            apps.append(app)
        self._write_all(apps)
        return app

    def delete(self, app_id: str) -> ManagedApp:
        apps = self._read_all()
        removed: ManagedApp | None = None
        remaining: list[ManagedApp] = []
        for app in apps:
            if app.id == app_id:
                removed = app
            else:
                remaining.append(app)
        if removed is None:
            raise AppNotFoundError(f"Aplicación '{app_id}' no encontrada.")
        self._write_all(remaining)
        return removed
