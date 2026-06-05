"""Einstellungen als JSON-Datei neben der Datenbank.

Ersetzt QSettings – alles liegt im gleichen Verzeichnis wie die DB.
Auf macOS wird das über iCloud synchronisiert.

Pfade:
  macOS:   ~/Library/Mobile Documents/com~apple~CloudDocs/CutStock/settings.json
  Windows: %APPDATA%/CutStock/settings.json
  Linux:   ~/.config/CutStock/settings.json (Fallback)
"""

from __future__ import annotations

import json
from pathlib import Path
from core.db import DEFAULT_DB

SETTINGS_FILE = DEFAULT_DB.parent / "settings.json"


class Settings:
    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self._data: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self):
        try:
            self.path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass

    def value(self, key: str, default=None, type=None):
        parts = key.split("/")
        obj = self._data
        for part in parts[:-1]:
            obj = obj.get(part, {})
            if not isinstance(obj, dict):
                return default
        val = obj.get(parts[-1], default)
        if type is not None and val is not None:
            try:
                val = type(val)
            except (ValueError, TypeError):
                return default
        return val

    def setValue(self, key: str, value):
        parts = key.split("/")
        obj = self._data
        for part in parts[:-1]:
            if part not in obj or not isinstance(obj[part], dict):
                obj[part] = {}
            obj = obj[part]
        if isinstance(value, bytes):
            import base64
            value = base64.b64encode(value).decode("ascii")
        obj[parts[-1]] = value
        self._save()

    def fileName(self) -> str:
        return str(self.path)


_instance: Settings | None = None


def get_settings() -> Settings:
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance
