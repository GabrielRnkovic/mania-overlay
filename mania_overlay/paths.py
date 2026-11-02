"""Turn the beatmap paths tosu reports (often Windows-style under Wine) into Linux paths."""
from __future__ import annotations

import os
import re
from pathlib import Path

_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)$")


def wine_prefixes(extra: str = "") -> list[Path]:
    home = Path.home()
    candidates = [
        extra,
        os.environ.get("WINEPREFIX", ""),
        # osu-winello
        str(home / ".local/share/wineprefixes/osu-wineprefix"),
        str(home / ".local/share/osu-wine/WINE.win32"),
        # osu-wine / older scripts
        str(home / ".local/share/osu-wine/prefix"),
        str(home / ".wine-osu"),
        str(home / ".wine"),
    ]
    seen, out = set(), []
    for c in candidates:
        if not c:
            continue
        p = Path(os.path.expanduser(c))
        if p not in seen and p.is_dir():
            seen.add(p)
            out.append(p)
    return out


def to_linux(path: str, wine_prefix: str = "") -> list[Path]:
    """All plausible Linux locations for a path that may be a Windows path."""
    if not path:
        return []
    path = path.strip()
    m = _DRIVE_RE.match(path)
    if not m:
        return [Path(path.replace("\\", "/"))]
    letter, rest = m.group(1).lower(), m.group(2).replace("\\", "/")
    out: list[Path] = []
    if letter == "z":
        out.append(Path("/") / rest)
    for prefix in wine_prefixes(wine_prefix):
        dos = prefix / "dosdevices" / f"{letter}:"
        if dos.exists():
            out.append(dos.resolve() / rest)
        if letter == "c":
            out.append(prefix / "drive_c" / rest)
    return out


def find_existing(paths: list[str], wine_prefix: str = "") -> Path | None:
    for raw in paths:
        for p in to_linux(raw, wine_prefix):
            if p.exists():
                return p
    return None


def beatmap_path(tosu: dict, settings: dict) -> Path | None:
    """Locate the current .osu file from a tosu /json/v2 payload."""
    gen = settings.get("general", {})
    prefix = gen.get("winePrefix", "")
    folders = tosu.get("folders") or {}
    files = tosu.get("files") or {}
    direct = tosu.get("directPath") or {}
    folder, file = folders.get("beatmap") or "", files.get("beatmap") or ""

    candidates = []
    if direct.get("beatmapFile"):
        candidates.append(direct["beatmapFile"])
    if folder and file:
        if gen.get("songsFolder"):
            candidates.append(os.path.join(os.path.expanduser(gen["songsFolder"]), folder, file))
        if folders.get("songs"):
            candidates.append(folders["songs"].rstrip("\\/") + "\\" + folder + "\\" + file)
        for songs in DEFAULT_SONGS_FOLDERS:
            candidates.append(os.path.join(os.path.expanduser(songs), folder, file))
    return find_existing(candidates, prefix)


# Where common Linux osu! installs keep their Songs folder (tried last).
DEFAULT_SONGS_FOLDERS = [
    "~/.local/share/osu-wine/osu!/Songs",          # osu-winello
    "~/.local/share/osu-wine/OSU/Songs",
    "~/.local/share/wineprefixes/osu-wineprefix/drive_c/osu!/Songs",
    "~/.wine-osu/drive_c/osu!/Songs",
]
