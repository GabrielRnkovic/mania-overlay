"""mania-overlay command line.

  mania-overlay                 start the overlay (same as `run`)
  mania-overlay edit            toggle edit mode (move widgets, settings, rate changer)
  mania-overlay rate-menu       open / close the rate picker (any rate 0.5x-2x)
  mania-overlay doctor          print sizes, scales and versions for a bug report
  mania-overlay toggle          show / hide the overlay
  mania-overlay rate 1.1 1.2    make rate-changed copies of the current map
  mania-overlay rate 1 --od 8   OD-only copy (any rate can take --od)
  mania-overlay rate-file MAP.osu 1.1 [--pitch] [--od 8]   same, for a file (no overlay needed)
  mania-overlay reload | quit
"""
from __future__ import annotations

import argparse
import ctypes.util
import json
import os
import sys
import urllib.error
import urllib.request

from .config import DEFAULT_PORT, Settings


def _post(port: int, route: str, body: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{route}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _ensure_layer_shell_preloaded() -> None:
    """gtk4-layer-shell must be loaded before libwayland-client, so re-exec with LD_PRELOAD."""
    if os.environ.get("MANIA_OVERLAY_PRELOADED"):
        return
    lib = ctypes.util.find_library("gtk4-layer-shell")
    if not lib:
        print("libgtk4-layer-shell not found. Install it with: sudo dnf install gtk4-layer-shell",
              file=sys.stderr)
        sys.exit(1)
    env = dict(os.environ, MANIA_OVERLAY_PRELOADED="1")
    env["LD_PRELOAD"] = ":".join(filter(None, [lib, env.get("LD_PRELOAD", "")]))
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = ":".join(filter(None, [pkg_parent, env.get("PYTHONPATH", "")]))
    os.execve(sys.executable, [sys.executable, "-m", "mania_overlay", *sys.argv[1:]], env)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mania-overlay", description="osu!mania overlay for Wayland (niri)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MANIA_OVERLAY_PORT", DEFAULT_PORT)))
    sub = ap.add_subparsers(dest="cmd")
    run_p = sub.add_parser("run", help="start the overlay")
    run_p.add_argument("--inspect", action="store_true", help="enable the WebKit inspector (right-click in edit mode)")
    run_p.add_argument("--demo", action="store_true", help="fake gameplay data, for testing without osu!/tosu")
    for name in ("edit", "rate-menu", "toggle", "show", "hide", "reload", "quit"):
        sub.add_parser(name)
    sub.add_parser("doctor", help="print sizes, scales and versions for bug reports")
    rate_p = sub.add_parser("rate", help="rate-change the map selected in osu!")
    rate_p.add_argument("rates", nargs="+", type=float)
    rate_p.add_argument("--pitch", action="store_true", default=None, help="change pitch (nightcore style)")
    rate_p.add_argument("--overwrite", action="store_true", default=None)
    rate_p.add_argument("--od", type=float, default=None, help="also set the map's OD (0-10)")
    file_p = sub.add_parser("rate-file", help="rate-change a specific .osu file")
    file_p.add_argument("osu")
    file_p.add_argument("rates", nargs="+", type=float)
    file_p.add_argument("--pitch", action="store_true")
    file_p.add_argument("--overwrite", action="store_true")
    file_p.add_argument("--od", type=float, default=None, help="also set the map's OD (0-10)")
    file_p.add_argument("--format", choices=["ogg", "mp3"], default="ogg")
    args = ap.parse_args(argv)
    cmd = args.cmd or "run"

    if cmd == "run":
        _ensure_layer_shell_preloaded()
        from . import overlay
        return overlay.run(Settings(), args.port, inspect=getattr(args, "inspect", False),
                           demo=getattr(args, "demo", False))

    if cmd == "doctor":
        from .doctor import report
        return report(args.port)

    if cmd == "rate-file":
        from .ratechanger import RateError, make_rate
        status = 0
        for r in args.rates:
            try:
                res = make_rate(args.osu, r, pitch=args.pitch, overwrite=args.overwrite,
                                audio_format=args.format, od=args.od)
                print(("exists:  " if res.skipped else "created: ") + str(res.osu_path))
            except RateError as e:
                print(f"{r}x: {e}", file=sys.stderr)
                status = 1
        return status

    try:
        if cmd == "rate":
            res = _post(args.port, "/api/rate", {"rates": args.rates, "pitch": args.pitch,
                                                 "overwrite": args.overwrite, "od": args.od})
            for r in res.get("results", []):
                print(("exists:  " if r["skipped"] else "created: ") + r["osu"])
            for e in res.get("errors", []) + ([res["error"]] if res.get("error") else []):
                print(e, file=sys.stderr)
            return 0 if res.get("ok") else 1
        res = _post(args.port, "/api/control", {"cmd": cmd}, timeout=5)
    except (urllib.error.URLError, ConnectionError) as e:
        print(f"overlay isn't running ({e}). Start it with: mania-overlay", file=sys.stderr)
        return 1
    if not res.get("ok"):
        print(res.get("error", "failed"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
