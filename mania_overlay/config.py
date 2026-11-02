"""Settings storage: ~/.config/mania-overlay/settings.json, merged over defaults."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

DEFAULT_PORT = 24055


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "mania-overlay"


DEFAULTS: dict = {
    "general": {
        "tosuHost": "127.0.0.1:24050",
        # Folder name of the ManiaMapAnalyser counter inside tosu's static folder.
        "analyserCounter": "ManiaMapAnalyser by Leo_Black",
        # Leave empty to auto-detect from tosu / the Wine prefix.
        "songsFolder": "",
        "winePrefix": "",
        # Connector name like "DP-1"; empty = compositor's choice. Applied live.
        "monitor": "",
        "gridSize": 8,
        "hideWhenDisconnected": True,
    },
    "rate": {
        "pitch": False,
        "audioFormat": "ogg",
        "overwrite": False,
        "lastRate": 1.1,   # what the rate picker opens with
        "lastOd": None,    # last OD typed in the picker (None = use the map's)
        "quickRates": [0.8, 0.85, 0.9, 0.95, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5],
    },
    "theme": {
        "font": "Inter, 'Noto Sans', 'DejaVu Sans', sans-serif",
        "textColor": "#ffffff",
        "accent": "#ff66aa",
        "panelColor": "#14141c",
        "panelOpacity": 0.55,
        "radius": 10,
        "textShadow": True,
        "colors": {
            "max": "#cfe8ff",
            "300": "#ffd24a",
            "200": "#5fe08a",
            "100": "#4aa3ff",
            "50": "#b48cff",
            "miss": "#ff4d5e",
        },
    },
    "widgets": {
        "judgements": {
            "enabled": True, "x": 40, "y": 380, "scale": 1.0, "opacity": 1.0,
            "showIn": "playing", "layout": "rows", "showRatios": True, "showBadge": True,
        },
        "pp": {
            "enabled": True, "x": 40, "y": 270, "scale": 1.0, "opacity": 1.0,
            "showIn": "playing+results", "showFc": True, "decimals": 0,
        },
        "ur": {
            "enabled": True, "x": 760, "y": 980, "scale": 1.0, "opacity": 1.0,
            "showIn": "playing", "showBar": True, "barWidth": 400, "barHistory": 40,
        },
        "stats": {
            "enabled": True, "x": 40, "y": 180, "scale": 1.0, "opacity": 1.0,
            "showIn": "playing", "showAcc": True, "showCombo": True,
        },
        "mapinfo": {
            "enabled": True, "x": 40, "y": 40, "scale": 1.0, "opacity": 1.0,
            "showIn": "select",
        },
        "analyser": {
            "enabled": True, "x": 1380, "y": 120, "scale": 0.8, "opacity": 1.0,
            "showIn": "always", "width": 520, "height": 680,
        },
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "settings.json")
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                return _merge(DEFAULTS, json.load(f))
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)
        except (OSError, ValueError) as e:
            print(f"[mania-overlay] could not read {self.path}: {e}; using defaults")
            return copy.deepcopy(DEFAULTS)

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.data)

    def replace(self, new: dict) -> dict:
        with self._lock:
            self.data = _merge(DEFAULTS, new)
            self._save()
            return copy.deepcopy(self.data)

    def reset(self) -> dict:
        return self.replace({})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)
