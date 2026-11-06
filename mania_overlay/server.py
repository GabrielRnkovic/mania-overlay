"""Local HTTP server: serves the overlay page and a small JSON API.

  GET  /api/settings          current settings
  POST /api/settings          replace settings (body: full settings object)
  POST /api/settings/reset    restore defaults
  GET  /api/status            edit mode, ffmpeg availability, current map path
  POST /api/control           {"cmd": "edit" | "edit-on" | "edit-off" | "rate-menu" | "rate-menu-on" | "rate-menu-off"
                               | "toggle" | "show" | "hide" | "reload" | "quit"}
  POST /api/rate              {"rates": [1.1, 1.2], "pitch": false, "overwrite": false, "od": 8 | null}
  GET  /api/monitors          outputs the overlay can be placed on (GTK host only)
  POST /api/analyser          where to draw the MSD/dan panel natively (GTK host only)

Only binds to 127.0.0.1.
"""
from __future__ import annotations

import json
import mimetypes
import shutil
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from . import paths, ratechanger
from .config import Settings

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


CLIENT_INFO: dict = {}   # last size report from the page


class Controller:
    """What the HTTP API can ask the overlay window to do. The GTK host overrides this."""

    edit_mode = False
    menu_mode = False
    native_analyser = False   # True when the host draws the MSD panel itself (sharp zoom)

    def control(self, cmd: str) -> dict:
        return {"ok": False, "error": "overlay window not running"}

    def monitors(self) -> list:
        return []

    def diagnostics(self) -> dict:
        """Window / monitor / toolkit facts for `mania-overlay doctor` (GTK host only)."""
        return {}

    def analyser(self, spec: dict) -> dict:
        return {"ok": False, "error": "no native host"}

    def notify(self, message: str, kind: str = "info") -> None:
        print(f"[mania-overlay] {message}")

    def settings_changed(self) -> None:
        pass


def fetch_tosu(host: str) -> dict:
    with urllib.request.urlopen(f"http://{host}/json/v2", timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))


def describe(rate: float, od: float | None) -> str:
    """Short label like "1.1x", "1.1x OD8" or "OD8"."""
    parts = []
    if not ratechanger.is_one(rate):
        parts.append(ratechanger.fmt_rate(rate) + "x")
    if od is not None:
        parts.append("OD" + ratechanger.fmt_od(od))
    return " ".join(parts) or "1x"


def create_rates(settings: dict, rates: list, pitch: bool | None = None,
                 overwrite: bool | None = None, notify: Callable[[str, str], None] | None = None,
                 od: float | None = None) -> dict:
    rate_cfg = settings.get("rate", {})
    pitch = rate_cfg.get("pitch", False) if pitch is None else pitch
    overwrite = rate_cfg.get("overwrite", False) if overwrite is None else overwrite
    if od is not None:
        try:
            od = float(od)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"bad OD value {od!r}"}
    try:
        tosu = fetch_tosu(settings["general"]["tosuHost"])
    except OSError as e:
        return {"ok": False, "error": f"can't reach tosu: {e}"}
    osu = paths.beatmap_path(tosu, settings)
    if not osu:
        return {"ok": False, "error": "couldn't find the current .osu file — set the Songs folder in General settings"}

    results, errors = [], []
    for r in rates:
        label = f"{r}x"
        try:
            label = describe(float(r), od)
            if notify:
                notify(f"Creating {label}…", "info")
            res = ratechanger.make_rate(osu, float(r), pitch=pitch, overwrite=overwrite,
                                        audio_format=rate_cfg.get("audioFormat", "ogg"), od=od)
            results.append(res.to_dict())
        except (ratechanger.RateError, ValueError, OSError) as e:
            errors.append(f"{label}: {e}")
    made = [describe(x["rate"], x["od"]) for x in results if not x["skipped"]]
    skipped = [describe(x["rate"], x["od"]) for x in results if x["skipped"]]
    if notify:
        if made:
            notify("Created " + ", ".join(made) + " — press F5 in song select if they don't show up", "ok")
        if skipped:
            notify("Already exists: " + ", ".join(skipped), "info")
        for e in errors:
            notify(e, "error")
    return {"ok": not errors, "map": str(osu), "results": results, "errors": errors}


def make_handler(settings: Settings, controller: Controller):
    class Handler(BaseHTTPRequestHandler):
        server_version = "mania-overlay"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route == "/api/settings":
                return self._json(settings.get())
            if route == "/api/status":
                return self._json({
                    "edit": controller.edit_mode,
                    "menu": controller.menu_mode,
                    "nativeAnalyser": controller.native_analyser,
                    "ffmpeg": shutil.which("ffmpeg") is not None,
                })
            if route == "/api/monitors":
                return self._json({"monitors": controller.monitors()})
            if route == "/api/doctor":
                from . import __version__
                return self._json({"version": __version__, "host": controller.diagnostics(),
                                   "page": CLIENT_INFO, "edit": controller.edit_mode})
            if route == "/api/current-map":
                s = settings.get()
                try:
                    p = paths.beatmap_path(fetch_tosu(s["general"]["tosuHost"]), s)
                except OSError as e:
                    return self._json({"path": None, "error": str(e)})
                return self._json({"path": str(p) if p else None})
            return self._static(route)

        def do_POST(self):
            route = self.path.split("?", 1)[0]
            try:
                body = self._body()
            except ValueError:
                return self._json({"ok": False, "error": "bad json"}, 400)
            if route == "/api/settings":
                data = settings.replace(body)
                controller.settings_changed()
                return self._json(data)
            if route == "/api/settings/reset":
                data = settings.reset()
                controller.settings_changed()
                return self._json(data)
            if route == "/api/client-info":
                # the page reports its own idea of its size, for `mania-overlay doctor`
                if isinstance(body, dict):
                    CLIENT_INFO.clear()
                    CLIENT_INFO.update({k: body[k] for k in list(body)[:20]})
                return self._json({"ok": True})
            if route == "/api/analyser":
                return self._json(controller.analyser(body if isinstance(body, dict) else {}))
            if route == "/api/control":
                return self._json(controller.control(str(body.get("cmd", ""))))
            if route == "/api/rate":
                rates = body.get("rates") or []
                if not isinstance(rates, list) or not rates:
                    return self._json({"ok": False, "error": "no rates given"}, 400)
                return self._json(create_rates(settings.get(), rates, body.get("pitch"),
                                               body.get("overwrite"), controller.notify, body.get("od")))
            return self._json({"ok": False, "error": "not found"}, 404)

        def _static(self, route: str):
            rel = route.lstrip("/") or "index.html"
            target = (WEB_DIR / rel).resolve()
            if WEB_DIR not in target.parents or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def start_server(port: int, settings: Settings, controller: Controller) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(settings, controller))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="mania-overlay-http", daemon=True).start()
    return httpd
