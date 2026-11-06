"""The overlay window: a fullscreen, transparent wlr-layer-shell surface holding a WebView.

Works on any compositor with wlr-layer-shell (niri, KDE Plasma/KWin, Hyprland, Sway...).

Normally the surface has an empty input region, so every click and key goes
straight to osu!. In edit mode (and while the rate picker is open) the input
region covers the screen and the surface takes the keyboard.

The MSD/dan panel (ManiaMapAnalyser, a separate tosu counter) is drawn by a
second WebView stacked on top of the page, using WebKit's real page zoom. A
CSS-scaled <iframe> would be rasterised at 1x and then stretched, which is
what made it blurry. The page tells us where to put it via POST /api/analyser.
"""
from __future__ import annotations

import json
import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("WebKit", "6.0")
gi.require_foreign("cairo")
import cairo  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, WebKit  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from .config import Settings  # noqa: E402
from .server import Controller, start_server  # noqa: E402

CSS = "window, window.background { background: transparent; }"


def _layer_shell_version() -> str:
    try:
        return f"{LayerShell.get_major_version()}.{LayerShell.get_minor_version()}.{LayerShell.get_micro_version()}"
    except AttributeError:
        return "?"


def idle(fn, *args):
    """Run fn on the GTK main thread (the HTTP server runs in its own thread)."""
    GLib.idle_add(lambda: (fn(*args), False)[1])


class OverlayController(Controller):
    native_analyser = True

    def __init__(self, app: "OverlayApp"):
        self.app = app

    @property
    def edit_mode(self):  # type: ignore[override]
        return self.app.edit

    @property
    def menu_mode(self):  # type: ignore[override]
        return self.app.menu

    def control(self, cmd: str) -> dict:
        actions = {
            "edit": lambda: self.app.set_edit(not self.app.edit),
            "edit-on": lambda: self.app.set_edit(True),
            "edit-off": lambda: self.app.set_edit(False),
            "rate-menu": lambda: self.app.set_menu(not self.app.menu),
            "rate-menu-on": lambda: self.app.set_menu(True),
            "rate-menu-off": lambda: self.app.set_menu(False),
            "toggle": lambda: self.app.set_visible(not self.app.visible),
            "show": lambda: self.app.set_visible(True),
            "hide": lambda: self.app.set_visible(False),
            "reload": self.app.reload,
            "quit": self.app.quit,
        }
        action = actions.get(cmd)
        if not action:
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        idle(action)
        return {"ok": True}

    def notify(self, message: str, kind: str = "info") -> None:
        print(f"[mania-overlay] {message}", flush=True)
        idle(self.app.js, f"window.overlay && overlay.toast({json.dumps(message)}, {json.dumps(kind)})")

    def settings_changed(self) -> None:
        idle(self.app.apply_monitor_setting)

    def monitors(self) -> list:
        return list(self.app.monitor_list)

    def analyser(self, spec: dict) -> dict:
        idle(self.app.set_analyser, spec)
        return {"ok": True}

    def diagnostics(self) -> dict:
        # GTK must be touched on its own thread: ask it and wait briefly
        out: dict = {}
        done = threading.Event()

        def collect():
            try:
                out.update(self.app.diagnostics())
            except Exception as e:  # never let a diagnostic crash the overlay
                out["error"] = repr(e)
            done.set()
        idle(collect)
        done.wait(3)
        return out


class OverlayApp(Gtk.Application):
    def __init__(self, settings: Settings, port: int, inspect: bool = False, demo: bool = False):
        super().__init__(application_id="io.github.maniaoverlay", flags=0)
        self.settings = settings
        self.port = port
        self.inspect = inspect
        self.demo = demo
        self.edit = False
        self.menu = False   # the rate picker popup
        self.visible = True
        self.win = None
        self.view = None
        self.stack = None          # Gtk.Overlay: page view + analyser view on top
        self.aview = None          # the native analyser WebView (created on first use)
        self.afixed = None         # Gtk.Fixed holding it
        self.aspec: dict = {}
        self.httpd = None
        self.monitor_list: list[dict] = []   # read by the HTTP thread, only replaced whole
        self.current_monitor = None          # connector we asked for ("" = compositor's choice)

    # ------------------------------------------------------------------ setup
    def do_activate(self):
        if self.win:
            return
        if not LayerShell.is_supported():
            print("[mania-overlay] this session doesn't support wlr-layer-shell. mania-overlay needs a "
                  "Wayland session (KDE Plasma Wayland, niri, Hyprland, Sway...) and must be started with "
                  "the `mania-overlay` launcher so the library is preloaded.", file=sys.stderr)
            self.quit()
            return

        try:
            self.httpd = start_server(self.port, self.settings, OverlayController(self))
        except OSError as e:
            print(f"[mania-overlay] can't listen on 127.0.0.1:{self.port}: {e} "
                  "(is another instance running?)", file=sys.stderr)
            self.quit()
            return

        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):  # GTK >= 4.12
            provider.load_from_string(CSS)
        else:
            provider.load_from_data(CSS.encode())
        display = Gdk.Display.get_default()
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        win = Gtk.ApplicationWindow(application=self)
        win.set_decorated(False)
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "mania-overlay")
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)  # above fullscreen windows
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(win, edge, True)
        LayerShell.set_exclusive_zone(win, -1)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)
        self.win = win

        monitors = display.get_monitors()
        monitors.connect("items-changed", lambda *_: self._monitors_changed())
        self._refresh_monitor_list()
        self.apply_monitor_setting(initial=True)

        view = self._make_view()
        ws = view.get_settings()
        ws.set_enable_developer_extras(self.inspect)
        view.connect("context-menu", lambda *a: not (self.inspect and self.edit))
        view.connect("load-changed", self._on_page_load)

        stack = Gtk.Overlay()
        stack.set_child(view)
        win.set_child(stack)

        self.view, self.stack = view, stack
        win.connect("realize", self._on_realize)
        view.load_uri(f"http://127.0.0.1:{self.port}/index.html" + ("?demo" if self.demo else ""))
        win.present()
        print(f"[mania-overlay] running — page at http://127.0.0.1:{self.port}/", flush=True)

    @staticmethod
    def _make_view() -> WebKit.WebView:
        view = WebKit.WebView()
        clear = Gdk.RGBA()
        clear.parse("rgba(0,0,0,0)")
        view.set_background_color(clear)
        view.get_settings().set_enable_write_console_messages_to_stdout(True)
        return view

    # ------------------------------------------------------------------ diagnostics
    def diagnostics(self) -> dict:
        self._refresh_monitor_list()
        win, view = self.win, self.view
        surface = win.get_surface() if win else None
        d = {
            "gtk": f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}",
            "webkit": f"{WebKit.get_major_version()}.{WebKit.get_minor_version()}.{WebKit.get_micro_version()}",
            "layerShell": _layer_shell_version(),
            "env": {k: os.environ.get(k, "") for k in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "GDK_SCALE",
                                                       "GDK_DPI_SCALE", "QT_SCALE_FACTOR", "WEBKIT_DISABLE_DMABUF_RENDERER")},
            "visible": self.visible, "edit": self.edit, "menu": self.menu,
            "monitorSetting": self.current_monitor,
            "window": [win.get_width(), win.get_height()] if win else None,
            "view": [view.get_width(), view.get_height()] if view else None,
            "viewZoom": view.get_zoom_level() if view else None,
            "monitors": self.monitor_list,
        }
        if surface:
            d["surfaceScaleFactor"] = surface.get_scale_factor()
            if hasattr(surface, "get_scale"):
                d["surfaceScale"] = round(surface.get_scale(), 4)   # fractional scale, GTK >= 4.12
            mon = Gdk.Display.get_default().get_monitor_at_surface(surface)
            if mon:
                g = mon.get_geometry()
                d["onMonitor"] = {"connector": mon.get_connector(), "x": g.x, "y": g.y,
                                  "width": g.width, "height": g.height, "scaleFactor": mon.get_scale_factor(),
                                  "scale": round(mon.get_scale(), 4) if hasattr(mon, "get_scale") else None}
        return d

    # ------------------------------------------------------------------ monitors
    def _refresh_monitor_list(self):
        out = []
        monitors = Gdk.Display.get_default().get_monitors()
        for i in range(monitors.get_n_items()):
            mon = monitors.get_item(i)
            geo = mon.get_geometry()
            if not mon.get_connector():
                continue   # not fully set up yet; picked up by the delayed refresh
            parts = [p for p in (mon.get_manufacturer(), mon.get_model()) if p and p.lower() != "unknown"]
            out.append({
                "connector": mon.get_connector(),
                "name": " ".join(parts) or (mon.get_description() or ""),
                "width": geo.width, "height": geo.height, "scale": mon.get_scale_factor(),
            })
        self.monitor_list = out

    def _monitors_changed(self):
        self._refresh_monitor_list()
        # a new monitor's properties arrive a moment after it is added
        GLib.timeout_add(1000, lambda: (self._refresh_monitor_list(), False)[1])
        # a monitor that was missing at startup may have just been plugged in
        self.current_monitor = None
        self.apply_monitor_setting()

    def apply_monitor_setting(self, initial: bool = False):
        if not self.win:
            return
        wanted = (self.settings.get()["general"].get("monitor") or "").strip()
        if wanted == self.current_monitor:
            return
        target = None
        if wanted:
            monitors = Gdk.Display.get_default().get_monitors()
            for i in range(monitors.get_n_items()):
                mon = monitors.get_item(i)
                if mon.get_connector() == wanted:
                    target = mon
                    break
            if target is None:
                print(f"[mania-overlay] monitor {wanted!r} not found; using the compositor's choice", flush=True)
        self.current_monitor = wanted
        if initial:
            LayerShell.set_monitor(self.win, target)
            return
        # move a live overlay: unmap, retarget, map again
        was_visible = self.win.get_visible()
        if was_visible:
            self.win.set_visible(False)
        LayerShell.set_monitor(self.win, target)
        if was_visible:
            self.win.set_visible(True)
            idle(self._apply_input_region)

    # ------------------------------------------------------------------ native analyser panel
    def set_analyser(self, spec: dict):
        """Place, size and zoom the MSD/dan panel. spec comes from the page (CSS px == GTK px)."""
        if not self.stack:
            return
        visible = bool(spec.get("visible")) and bool(spec.get("src"))
        if not visible:
            if self.aview:
                self.aview.set_visible(False)
            self.aspec = spec
            return
        av = self.aview
        x = max(0, int(round(float(spec.get("x") or 0))))
        y = max(0, int(round(float(spec.get("y") or 0))))
        if av is None:
            # A Gtk.Fixed gives children exactly their size request at exact
            # coordinates. It is untargetable, so clicks and scrolls reach the
            # page below (dragging the panel in edit mode still works).
            fixed = Gtk.Fixed()
            fixed.set_can_target(False)
            fixed.set_focusable(False)
            self.stack.add_overlay(fixed)
            av = self._make_view()
            av.set_can_target(False)
            av.set_focusable(False)
            av.set_can_focus(False)
            fixed.put(av, x, y)
            self.afixed, self.aview = fixed, av
        zoom = min(4.0, max(0.25, float(spec.get("zoom") or 1)))
        width = max(50, int(round(float(spec.get("width") or 520) * zoom)))
        height = max(50, int(round(float(spec.get("height") or 680) * zoom)))
        av.set_size_request(width, height)
        self.afixed.move(av, x, y)
        av.set_opacity(min(1.0, max(0.0, float(spec.get("opacity", 1)))))
        if abs(av.get_zoom_level() - zoom) > 1e-3:
            av.set_zoom_level(zoom)
        old = self.aspec
        if spec.get("src") != old.get("src") or spec.get("gen") != old.get("gen") or not av.get_uri():
            av.load_uri(spec["src"])
        av.set_visible(True)
        self.aspec = spec

    def _on_page_load(self, _view, event):
        # the page is (re)loading: hide the panel until the page places it again
        if event == WebKit.LoadEvent.STARTED and self.aview:
            self.aview.set_visible(False)
            self.aspec = {}

    # ------------------------------------------------------------------ input
    def _on_realize(self, win):
        surface = win.get_surface()
        surface.connect("layout", lambda *_: self._apply_input_region())
        self._apply_input_region()

    @property
    def interactive(self) -> bool:
        return self.edit or self.menu

    def _apply_input_region(self):
        if not self.win or not self.win.get_surface():
            return
        if self.interactive:
            region = cairo.Region(cairo.RectangleInt(0, 0, 1 << 15, 1 << 15))
        else:
            region = cairo.Region()  # empty: fully click-through
        self.win.get_surface().set_input_region(region)

    def _apply_interaction(self):
        """Take or release the keyboard and pointer to match edit / menu mode."""
        LayerShell.set_keyboard_mode(
            self.win, LayerShell.KeyboardMode.EXCLUSIVE if self.interactive else LayerShell.KeyboardMode.NONE)
        self._apply_input_region()
        if self.interactive and self.view:
            self.view.grab_focus()

    # ------------------------------------------------------------------ state
    def set_edit(self, on: bool):
        if on and self.menu:
            self.menu = False
            self.js("window.overlay && overlay.setMenuMode(false)")
        self.edit = on
        if on and not self.visible:
            self.set_visible(True)
        self._apply_interaction()
        self.js(f"window.overlay && overlay.setEditMode({'true' if on else 'false'})")

    def set_menu(self, on: bool):
        if on and self.edit:
            self.edit = False
            self.js("window.overlay && overlay.setEditMode(false)")
        self.menu = on
        if on and not self.visible:
            self.set_visible(True)
        self._apply_interaction()
        self.js(f"window.overlay && overlay.setMenuMode({'true' if on else 'false'})")

    def set_visible(self, on: bool):
        if not on and self.interactive:
            # hiding while the editor or picker is open would leave the keyboard grabbed
            if self.edit:
                self.set_edit(False)
            if self.menu:
                self.set_menu(False)
        self.visible = on
        self.win.set_visible(on)
        if on:
            idle(self._apply_input_region)

    def reload(self):
        self.view.reload()
        if self.aview and self.aspec.get("src"):
            self.aview.reload()

    def js(self, code: str):
        if self.view:
            self.view.evaluate_javascript(code, -1, None, None, None, None, None)

    def do_shutdown(self):
        if self.httpd:
            self.httpd.shutdown()
        Gtk.Application.do_shutdown(self)


def run(settings: Settings, port: int, inspect: bool = False, demo: bool = False) -> int:
    return OverlayApp(settings, port, inspect, demo).run([sys.argv[0]])
