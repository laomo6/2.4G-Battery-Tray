"""Tiny JSON configuration.  Never a log file."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_NAME = "2.4GBatteryTray"
DEFAULT_INTERVAL = 60
MIN_INTERVAL = 30
MAX_INTERVAL = 1800

DEFAULTS = {
    "interval": DEFAULT_INTERVAL,
    "calibrations": {},
    "last": {},
    "names": {},
}


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or (app_dir() / "config.json")
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                merged = dict(DEFAULTS)
                merged.update(data)
                self.data = merged
        except Exception:
            self.data = dict(DEFAULTS)
        self.data["interval"] = self.clamp_interval(self.data.get("interval", DEFAULT_INTERVAL))

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".cfg-", suffix=".json", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        except Exception:
            # A read-only profile should not stop the tray.
            pass

    @staticmethod
    def clamp_interval(value) -> int:
        try:
            n = int(value)
        except Exception:
            n = DEFAULT_INTERVAL
        return max(MIN_INTERVAL, min(MAX_INTERVAL, n))

    @property
    def interval(self) -> int:
        return self.clamp_interval(self.data.get("interval", DEFAULT_INTERVAL))

    def set_interval(self, seconds: int):
        self.data["interval"] = self.clamp_interval(seconds)
        self.save()

    def calibration(self, slot: str) -> dict:
        c = self.data.get("calibrations")
        if isinstance(c, dict):
            value = c.get(slot)
            if isinstance(value, dict):
                return value
        return {}

    def set_calibration(self, slot: str, value: dict | None):
        c = self.data.setdefault("calibrations", {})
        if value:
            c[slot] = value
        else:
            c.pop(slot, None)
        self.save()

    def last(self, slot: str) -> dict:
        c = self.data.get("last")
        if isinstance(c, dict):
            value = c.get(slot)
            if isinstance(value, dict):
                return value
        return {}

    def set_last(self, slot: str, percent: int, ts: float):
        c = self.data.setdefault("last", {})
        c[slot] = {"percent": int(percent), "ts": float(ts)}
        self.save()

    def display_name(self, slot: str) -> str:
        names = self.data.get("names")
        if isinstance(names, dict):
            value = names.get(slot)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
