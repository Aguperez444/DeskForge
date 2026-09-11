"""Atomic JSON persistence for user configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

from deskforge.domain.models import AppConfig


class ConfigRepository:
    """Loads and saves AppConfig atomically."""

    def __init__(self, config_file: Path) -> None:
        self._config_file = config_file

    def load(self) -> AppConfig:
        if not self._config_file.exists():
            return AppConfig()
        try:
            raw = json.loads(self._config_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return AppConfig.from_dict(raw)
        except (OSError, json.JSONDecodeError):
            pass
        return AppConfig()

    def save(self, config: AppConfig) -> None:
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._config_file.with_suffix(".json.tmp")
        payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
        tmp_path.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp_path, self._config_file)
