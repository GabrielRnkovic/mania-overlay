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


# Bump when a release changes how saved settings should look; see _migrate().
SETTINGS_VERSION = 2

# Judgement colours from breadles5's "Mania Hit Count and Chart" counter.
JUDGEMENT_COLORS = {
    "max": "#88c6ff",
    "300": "#ffff00",
    "200": "#00ff00",
    "100": "#2274c0",
    "50": "#ff00ff",
    "miss": "#ff0000",
}
OLD_JUDGEMENT_COLORS = {  # the defaults before 0.4.0
    "max": "#cfe8ff", "300": "#ffd24a", "200": "#5fe08a",
    "100": "#4aa3ff", "50": "#b48cff", "miss": "#ff4d5e",
}

DEFAULTS: dict = {
    "version": SETTINGS_VERSION,
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
        "colors": dict(JUDGEMENT_COLORS),
    },
    "widgets": {
        "judgements": {
            "enabled": True, "x": 40, "y": 380, "scale": 1.0, "opacity": 1.0,
            "showIn": "playing", "layout": "chart", "labels": "words", "roundFont": True,
            "showRatios": False, "showBadge": False,
        },
        "pp": {
            "enabled": True, "x": 40, "y": 270, "scale": 1.0, "opacity": 1.0,
            "showIn": "playing+results", "showFc": True, "decimals": 0,
        },
        "ur": {
            "enabled": True, "x": 910, "y": 960, "scale": 1.0, "opacity": 1.0,
            "showIn": "playing", "showUr": True, "showEarlyLate": True,
            "barWidth": 100, "barRange": "200", "barHistory": 30, "colorTicks": False, "showZones": False,
            "panel": False, "centerColor": "#ff3b5c",
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


def _migrate(saved: dict) -> dict:
    """Update settings saved by an older version (before merging with DEFAULTS)."""
    saved = copy.deepcopy(saved) if isinstance(saved, dict) else {}
    version = saved.get("version", 1)
    if version < 2:
        # 0.4.0: new judgement counter (chart + counts) and slim UR bar
        widgets = saved.setdefault("widgets", {})
        j = widgets.setdefault("judgements", {})
        if j.get("layout", "rows") == "rows":
            j["layout"] = "chart"
        j["showRatios"] = False
        j["showBadge"] = False
        ur = widgets.setdefault("ur", {})
        if ur.get("barWidth", 400) == 400:      # untouched old default: the new bar is slim
            ur["barWidth"] = 100
            if ur.get("x") == 760:              # and keep it centred where the old one was
                ur["x"] = 910
        ur.pop("showBar", None)
        ur.pop("barHistory", None)
        colors = saved.get("theme", {}).get("colors")
        if colors is not None and all(colors.get(k, v) == v for k, v in OLD_JUDGEMENT_COLORS.items()):
            saved["theme"]["colors"] = dict(JUDGEMENT_COLORS)
        saved["version"] = 2
    return saved


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "settings.json")
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
            data = _merge(DEFAULTS, _migrate(saved))
            if saved.get("version") != data["version"]:
                self.data = data
                try:
                    self._save()
                except OSError:
                    pass
            return data
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
