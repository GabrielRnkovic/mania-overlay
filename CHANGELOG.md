# Changelog

## 0.4.2

- `mania-overlay doctor`: prints the overlay window's size and scale, the size the page lays out at,
  monitors, versions and `kscreen-doctor -o` / `niri msg outputs`, and points out mismatches. For bug
  reports about the overlay being too small, squashed or on the wrong screen.

## 0.4.1

- Installer: if GitHub's API refuses (it allows 60 requests an hour per network), tosu and
  ManiaMapAnalyser are found through the normal release page instead. Clearer error when GitHub
  can't be reached, and no more misleading "stopped at line …" message. `GITHUB_TOKEN` is used if set.

## 0.4.0

- New judgement counter in the style of breadles5's Mania Hit Count and Chart: doughnut chart of the
  judgement split next to marv / perf / great / good / bad / miss counts, with that counter's colours and a
  rounded font. Layouts: chart + counts, counts only, one line. Ratios and badge are now optional (off).
- New hit error bar: slim and see-through, fading white ticks, coloured centre line, average arrow and
  early / late counts (toggle). Options for bar range, colouring ticks by judgement, zones and a panel.
- Existing settings are migrated once: the old layouts switch to the new look, untouched default colours
  and bar width are updated; positions and anything you customised are kept.

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
