"""`mania-overlay doctor`: print what's needed to debug size, scale and placement problems."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from . import __version__


def _get(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=6) as r:
        return json.load(r)


def _run(cmd: list[str], lines: int = 40) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return "\n".join(out.splitlines()[:lines])


def report(port: int) -> int:
    print(f"mania-overlay {__version__}")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    print(f"desktop: {desktop or '?'}   session: {os.environ.get('XDG_SESSION_TYPE', '?')}")
    pkgs = _run(["rpm", "-q", "gtk4", "gtk4-layer-shell", "webkitgtk6.0", "kwin", "niri"])
    if pkgs:
        print("packages:\n  " + pkgs.replace("\n", "\n  "))

    problems: list[str] = []
    try:
        d = _get(port, "/api/doctor")
    except (urllib.error.URLError, OSError) as e:
        print(f"\noverlay: not running on port {port} ({e})")
        d = None
    if d:
        host, page = d.get("host") or {}, d.get("page") or {}
        print(f"\noverlay {d.get('version')}: GTK {host.get('gtk')}, WebKitGTK {host.get('webkit')}, "
              f"gtk4-layer-shell {host.get('layerShell')}")
        print(f"  window (GTK, logical px):   {host.get('window')}")
        print(f"  web view (GTK, logical px): {host.get('view')}   page zoom: {host.get('viewZoom')}")
        print(f"  surface scale: {host.get('surfaceScale')} (integer factor {host.get('surfaceScaleFactor')})")
        print(f"  on monitor: {host.get('onMonitor')}")
        print(f"  monitor setting: {host.get('monitorSetting')!r}")
        print(f"  page thinks: {page.get('innerWidth')}x{page.get('innerHeight')} CSS px, "
              f"devicePixelRatio {page.get('dpr')}, screen {page.get('screenWidth')}x{page.get('screenHeight')}, "
              f"visual zoom {page.get('visualScale')}")
        for m in host.get("monitors") or []:
            print(f"  monitor {m.get('connector')}: {m.get('width')}x{m.get('height')} scale {m.get('scale')} {m.get('name')}")
        env = {k: v for k, v in (host.get("env") or {}).items() if v}
        if env:
            print(f"  env: {env}")

        view, mon = host.get("view") or [0, 0], host.get("onMonitor") or {}
        if page.get("innerWidth") and view[0] and abs(page["innerWidth"] - view[0]) > 2:
            problems.append(f"the page lays out at {page['innerWidth']} px wide but its view is {view[0]} px: "
                            "WebKit and GTK disagree about the size (scaling problem)")
        if mon.get("width") and view[0] and abs(mon["width"] - view[0]) > 2:
            problems.append(f"the overlay is {view[0]} px wide but its monitor is {mon['width']} px")
        # GTK rounds scales below 1 up to 1, so a sub-100% display shows up as the overlay
        # being more logical pixels wide than the monitor's real resolution (see kscreen-doctor below)
        scale = host.get("surfaceScale") or mon.get("scale")
        if scale and scale < 1:
            problems.append(f"display scale is {scale} (below 100%), which many apps mishandle")
        if host.get("viewZoom") and abs(host["viewZoom"] - 1) > 1e-3:
            problems.append(f"the page is zoomed to {host['viewZoom']}")

    if "KDE" in desktop.upper():
        out = _run(["kscreen-doctor", "-o"], 60)
        if out:
            print("\nkscreen-doctor -o:\n" + out)
    elif "NIRI" in desktop.upper():
        out = _run(["niri", "msg", "outputs"], 60)
        if out:
            print("\nniri msg outputs:\n" + out)

    print("\n" + ("problems found:\n  - " + "\n  - ".join(problems) if problems else "no obvious problems found"))
    print("\nPaste all of this into a bug report.")
    return 0
