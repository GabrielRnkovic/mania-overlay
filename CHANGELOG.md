# Changelog

## 0.3.0

- Fedora installer (`install.sh`) for KDE Plasma and niri. It installs system packages, tosu,
  ManiaMapAnalyser and the overlay; sets up start on login; registers shortcuts. No config editing needed.
- KDE Plasma support, including global shortcuts that show up in System Settings → Shortcuts.
- niri: shortcuts live in `~/.config/niri/mania-overlay.kdl`, pulled in with one `include` line.
- Rate changer can change a map's OD, together with the rate or on its own (`--od` on the command line).
- MSD / dan panel is drawn by its own WebView with real page zoom, so it's sharp at any size.
- Monitor dropdown in the editor; switching monitors applies immediately.
- `mania-overlay run --demo` for trying the overlay without osu!.
- Finds the Songs folder of osu-winello installs automatically.

## 0.2.0

- Rate picker popup (`mania-overlay rate-menu`): any rate from 0.5x to 2x.

## 0.1.0

- First version: judgements, pp, UR / hit error bar, accuracy / combo, map info, MSD panel, rate changer, editor.
