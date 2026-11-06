#!/usr/bin/env bash
# mania-overlay installer for Fedora (KDE Plasma or niri).
#
# Installs everything the overlay needs, even on a fresh system:
#   - system packages (GTK4, gtk4-layer-shell, WebKitGTK, ffmpeg)
#   - tosu (reads osu!'s memory) and ManiaMapAnalyser (the MSD / dan panel)
#   - mania-overlay itself, started automatically when you log in
#   - global shortcuts: KDE System Settings entries, or a niri include file
#
# Run it from a clone:      ./install.sh
# or straight from GitHub:  bash <(curl -fsSL https://raw.githubusercontent.com/GabrielRnkovic/mania-overlay/main/install.sh)
#
# Re-running it updates everything and keeps your settings.
# Uninstall with:           ./install.sh --uninstall
set -Eeuo pipefail

REPO="${MANIA_REPO:-GabrielRnkovic/mania-overlay}"
BRANCH="${MANIA_BRANCH:-main}"
TOSU_REPO="tosuapp/tosu"
ANALYSER_REPO="LeoBlackMT/osumania_map_analyser"
ANALYSER_DIRNAME="ManiaMapAnalyser by Leo_Black"
OSU_WINELLO_REPO="https://github.com/NelloKudo/osu-winello.git"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_DIR="$DATA_HOME/mania-overlay"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/mania-overlay"
TOSU_DIR="$APP_DIR/tosu"
UNIT_DIR="$CONFIG_HOME/systemd/user"
AUTOSTART_DIR="$CONFIG_HOME/autostart"
DESKTOP_FILE="$DATA_HOME/applications/io.github.maniaoverlay.desktop"
# KDE's shortcut daemon also reads this folder at login (all Plasma versions; 6.1+ picks up the
# app-menu copy above immediately)
KGLOBALACCEL_FILE="$DATA_HOME/kglobalaccel/io.github.maniaoverlay.desktop"
NIRI_DIR="$CONFIG_HOME/niri"
NIRI_INCLUDE_FILE="$NIRI_DIR/mania-overlay.kdl"
STATE_FILE="$APP_DIR/install.env"
OS_RELEASE="${MANIA_OS_RELEASE:-/etc/os-release}"   # overridable for tests

# shortcuts: action id, command arguments, KDE key, niri key, description
SHORTCUTS=(
  "edit|edit|Meta+Alt+O|Mod+Alt+O|Open / close the editor"
  "rate-menu|rate-menu|Meta+Alt+R|Mod+Alt+R|Rate changer (any rate 0.5x-2x, OD)"
  "toggle|toggle|Meta+Alt+H|Mod+Alt+H|Show / hide the overlay"
  "quick-rate-1|rate 1.1|Meta+Alt+1|Mod+Alt+1|Make a 1.1x copy of the selected map"
  "quick-rate-2|rate 1.2|Meta+Alt+2|Mod+Alt+2|Make a 1.2x copy of the selected map"
)

# ----------------------------------------------------------------------------- options
OPT_DESKTOP=""
OPT_YES=0
OPT_TOSU=""          # yes / no / "" (ask)
OPT_ANALYSER=""
OPT_AUTOSTART=""
OPT_UNINSTALL=0
TOSU_ARCHIVE=""      # use a local tosu archive instead of downloading
ANALYSER_ARCHIVE=""

usage() {
  cat <<EOF
mania-overlay installer for Fedora

Usage: install.sh [options]

  --desktop kde|niri     don't ask which desktop you use
  -y, --yes              accept the default answer to every question
  --no-tosu              don't install or update tosu
  --no-analyser          don't install or update ManiaMapAnalyser
  --no-autostart         don't start anything automatically on login
  --tosu-archive FILE    install tosu from a downloaded release archive
  --analyser-archive FILE  install ManiaMapAnalyser from a downloaded zip
  --uninstall            remove mania-overlay (asks before removing settings)
  -h, --help             show this help
EOF
}

ORIG_ARGS=("$@")
while [[ $# -gt 0 ]]; do
  case "$1" in
    --desktop) OPT_DESKTOP="${2:-}"; shift 2 ;;
    --desktop=*) OPT_DESKTOP="${1#*=}"; shift ;;
    -y|--yes) OPT_YES=1; shift ;;
    --no-tosu) OPT_TOSU=no; shift ;;
    --no-analyser) OPT_ANALYSER=no; shift ;;
    --no-autostart) OPT_AUTOSTART=no; shift ;;
    --tosu-archive) TOSU_ARCHIVE="${2:-}"; shift 2 ;;
    --analyser-archive) ANALYSER_ARCHIVE="${2:-}"; shift 2 ;;
    --uninstall) OPT_UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# ----------------------------------------------------------------------------- output helpers
if [[ -t 1 ]]; then
  C_B=$'\e[1m'; C_DIM=$'\e[2m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_C=$'\e[36m'; C_0=$'\e[0m'
else
  C_B=""; C_DIM=""; C_G=""; C_Y=""; C_R=""; C_C=""; C_0=""
fi
step() { printf '\n%s==> %s%s\n' "$C_B$C_C" "$*" "$C_0"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '    %s✓%s %s\n' "$C_G" "$C_0" "$*"; }
warn() { printf '    %s!%s %s\n' "$C_Y" "$C_0" "$*"; }
die()  { printf '\n%sError:%s %s\n' "$C_R$C_B" "$C_0" "$*" >&2; exit 1; }
trap 'die "the installer stopped at line $LINENO (exit code $?). Nothing after that step was changed."' ERR

TTY=/dev/tty
have_tty() { [[ -r $TTY ]] && { : <"$TTY"; } 2>/dev/null; }

# ask "Question" default(y/n) -> returns 0 for yes
ask() {
  local q="$1" def="$2" ans hint
  [[ $def == y ]] && hint="[Y/n]" || hint="[y/N]"
  if [[ $OPT_YES == 1 ]] || ! have_tty; then
    printf '    %s %s %s\n' "$q" "$hint" "${C_DIM}(default: $def)${C_0}"
    [[ $def == y ]]; return
  fi
  while true; do
    printf '    %s %s ' "$q" "$hint"
    read -r ans <"$TTY" || ans=""
    ans="${ans,,}"
    [[ -z $ans ]] && ans="$def"
    case "$ans" in y|yes) return 0 ;; n|no) return 1 ;; esac
  done
}

# choose "Question" default_index option1 option2 ... -> echoes chosen index (1-based)
choose() {
  local q="$1" def="$2"; shift 2
  local i=1 ans
  printf '    %s\n' "$q" >&2
  for o in "$@"; do printf '      %d) %s\n' "$i" "$o" >&2; i=$((i + 1)); done
  if [[ $OPT_YES == 1 ]] || ! have_tty; then
    printf '    Using %d.\n' "$def" >&2; echo "$def"; return
  fi
  while true; do
    printf '    Choice [%d]: ' "$def" >&2
    read -r ans <"$TTY" || ans=""
    [[ -z $ans ]] && ans="$def"
    if [[ $ans =~ ^[0-9]+$ ]] && (( ans >= 1 && ans <= $# )); then echo "$ans"; return; fi
  done
}

TMP=""
cleanup() { [[ -n $TMP && -d $TMP ]] && rm -rf "$TMP"; return 0; }
trap cleanup EXIT
tmpdir() { [[ -n $TMP ]] || TMP="$(mktemp -d -t mania-overlay-install.XXXXXX)"; }

# state from a previous run, so re-running keeps the same answers by default
PREV_DESKTOP="" PREV_TOSU="" PREV_ANALYSER="" PREV_STATIC=""
load_state() {
  [[ -f $STATE_FILE ]] || return 0
  PREV_DESKTOP="$(sed -n 's/^DESKTOP=//p' "$STATE_FILE")"
  PREV_TOSU="$(sed -n 's/^TOSU_MANAGED=//p' "$STATE_FILE")"
  PREV_ANALYSER="$(sed -n 's/^ANALYSER_MANAGED=//p' "$STATE_FILE")"
  PREV_STATIC="$(sed -n 's/^STATIC_DIR=//p' "$STATE_FILE")"
}

systemd_user_ok() { command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; }
in_graphical_session() { [[ -n ${WAYLAND_DISPLAY:-} ]]; }
overlay_running() { curl -fs -m 1 http://127.0.0.1:24055/api/status >/dev/null 2>&1; }

# ----------------------------------------------------------------------------- niri config helpers
niri_config() { echo "$NIRI_DIR/config.kdl"; }

niri_supports_include() {
  command -v niri >/dev/null || return 1
  local v major minor
  v="$(niri --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -n1)" || return 1
  [[ -n $v ]] || return 1
  major="${v%%.*}"; minor="${v#*.}"
  (( major > 25 || (major == 25 && minor >= 11) ))
}

niri_validate() {
  command -v niri >/dev/null || return 0
  niri validate -c "$(niri_config)" >/dev/null 2>"$1"
}

# ----------------------------------------------------------------------------- uninstall
uninstall() {
  load_state
  step "Uninstalling mania-overlay"
  if systemd_user_ok; then
    for u in mania-overlay.service mania-overlay-tosu.service; do
      systemctl --user disable --now "$u" >/dev/null 2>&1 || true
      rm -f "$UNIT_DIR/$u"
    done
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  else
    rm -f "$UNIT_DIR/mania-overlay.service" "$UNIT_DIR/mania-overlay-tosu.service"
  fi
  overlay_running && "$BIN" quit >/dev/null 2>&1 || true
  rm -f "$AUTOSTART_DIR/mania-overlay.desktop" "$AUTOSTART_DIR/mania-overlay-tosu.desktop"
  ok "stopped it and removed autostart"

  if [[ -f $DESKTOP_FILE || -f $KGLOBALACCEL_FILE ]]; then
    rm -f "$DESKTOP_FILE" "$KGLOBALACCEL_FILE"
    command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true
    ok "removed the KDE shortcuts and menu entry"
  fi

  local cfg; cfg="$(niri_config)"
  if [[ -f $NIRI_INCLUDE_FILE ]] || { [[ -f $cfg ]] && grep -q 'include "mania-overlay.kdl"' "$cfg"; }; then
    if [[ -f $cfg ]] && grep -q 'include "mania-overlay.kdl"' "$cfg"; then
      cp "$cfg" "$cfg.mania-backup-$(date +%Y%m%d-%H%M%S)"
      sed -i '/^\/\/ Added by mania-overlay/d; /^include "mania-overlay.kdl"$/d' "$cfg"
    fi
    rm -f "$NIRI_INCLUDE_FILE"
    ok "removed the niri shortcuts (config.kdl backed up first)"
  fi

  rm -f "$BIN"
  local static="${PREV_STATIC:-$DATA_HOME/tosu/static}"
  if [[ ${PREV_ANALYSER:-} == yes && -d "$static/$ANALYSER_DIRNAME" ]]; then
    if ask "Also remove ManiaMapAnalyser from tosu's counters?" n; then
      rm -rf "${static:?}/$ANALYSER_DIRNAME"; ok "removed ManiaMapAnalyser"
    fi
  fi
  rm -rf "${APP_DIR:?}"
  ok "removed the app (and the tosu copy it installed) from $APP_DIR"
  if [[ -d $CONFIG_HOME/mania-overlay ]] && ask "Also delete your overlay layout and settings?" n; then
    rm -rf "${CONFIG_HOME:?}/mania-overlay"; ok "deleted settings"
  fi
  info "System packages (GTK, WebKit, ffmpeg) and tosu's own settings in ~/.config/tosu were left alone."
  printf '\n%sDone.%s\n' "$C_G$C_B" "$C_0"
}

# ----------------------------------------------------------------------------- install steps
check_system() {
  step "Checking your system"
  [[ $EUID -ne 0 ]] || die "run this as your normal user, not with sudo. It asks for your password when it needs it."
  [[ -r $OS_RELEASE ]] || die "can't read $OS_RELEASE"
  local id id_like name
  id="$(sed -n 's/^ID=//p' "$OS_RELEASE" | tr -d '"')"
  id_like="$(sed -n 's/^ID_LIKE=//p' "$OS_RELEASE" | tr -d '"')"
  name="$(sed -n 's/^PRETTY_NAME=//p' "$OS_RELEASE" | tr -d '"')"
  if [[ $id != fedora && " $id_like " != *" fedora "* ]]; then
    die "this installer is for Fedora only for now (found: ${name:-unknown}). See the README for the packages it needs."
  fi
  ok "${name:-Fedora}"
  command -v curl >/dev/null || die "curl is missing. Install it with: sudo dnf install curl"
  if [[ ${XDG_SESSION_TYPE:-} == x11 ]]; then
    warn "you're in an X11 session. The overlay needs a Wayland session (log in with \"Plasma (Wayland)\" or niri)."
  fi
}

choose_desktop() {
  step "Desktop"
  local detected="${OPT_DESKTOP:-}"
  if [[ -z $detected ]]; then
    case "${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_DESKTOP:-}:${DESKTOP_SESSION:-}" in
      *KDE*|*kde*|*plasma*) detected=kde ;;
      *niri*) detected=niri ;;
      *) detected="${PREV_DESKTOP:-}" ;;
    esac
  fi
  if [[ -n $OPT_DESKTOP ]]; then
    case "$OPT_DESKTOP" in kde|plasma|KDE) DESKTOP=kde ;; niri) DESKTOP=niri ;; *) die "--desktop must be kde or niri" ;; esac
  else
    local def=1
    [[ $detected == niri ]] && def=2
    [[ -n $detected ]] && info "Looks like you're using $([[ $detected == kde ]] && echo 'KDE Plasma' || echo niri)."
    case "$(choose "Which desktop do you use?" "$def" "KDE Plasma" "niri")" in
      1) DESKTOP=kde ;; 2) DESKTOP=niri ;;
    esac
  fi
  ok "$([[ $DESKTOP == kde ]] && echo 'KDE Plasma' || echo niri)"
}

install_packages() {
  step "System packages"
  local want=(python3 python3-gobject python3-cairo gtk4 gtk4-layer-shell webkitgtk6.0 unzip tar libcap)
  local missing=()
  for p in "${want[@]}"; do rpm -q "$p" >/dev/null 2>&1 || missing+=("$p"); done
  # any ffmpeg works (ffmpeg-free from Fedora, or ffmpeg from RPM Fusion); don't swap one for the other
  command -v ffmpeg >/dev/null || missing+=(ffmpeg-free)
  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "everything is already installed"
    return
  fi
  info "Installing: ${missing[*]}"
  info "(sudo will ask for your password)"
  sudo dnf install -y "${missing[@]}" || die "dnf couldn't install the packages above."
  ok "installed"
}

# Run from a git clone that's behind GitHub? Offer to pull, then restart with the new installer.
# (Otherwise re-running ./install.sh without `git pull` quietly reinstalls the old version.)
self_update() {
  [[ -n ${MANIA_UPDATED:-} ]] && return 0
  local here behind
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  [[ -n $here && -d $here/.git && -f $here/install.sh ]] || return 0
  command -v git >/dev/null || return 0
  git -C "$here" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1 || return 0
  if ! git -C "$here" fetch -q 2>/dev/null; then
    warn "couldn't check GitHub for a newer version; installing what's in this folder."
    return 0
  fi
  behind="$(git -C "$here" rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)"
  [[ $behind =~ ^[0-9]+$ && $behind -gt 0 ]] || return 0
  step "Update available"
  info "This folder is $behind update(s) behind GitHub."
  if ! ask "Download them first (git pull)?" y; then
    warn "installing the older version that's in this folder."
    return 0
  fi
  if ! git -C "$here" pull -q --ff-only; then
    warn "git pull didn't work (changed files in this folder?). Installing the version that's here."
    info "To get the update anyway: cd \"$here\" && git stash && git pull"
    return 0
  fi
  ok "updated: $(git -C "$here" log -1 --format=%s | cut -c1-70)"
  info "Restarting the installer with the new version…"
  MANIA_UPDATED=1 exec bash "$here/install.sh" "${ORIG_ARGS[@]}"
}

get_source() {
  step "mania-overlay"
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
  if [[ -n $here && -f $here/mania_overlay/__main__.py && -d $here/web ]]; then
    SRC="$here"
    info "Installing from $SRC"
  else
    tmpdir
    info "Downloading $REPO ($BRANCH)…"
    curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" -o "$TMP/src.tar.gz" \
      || die "couldn't download https://github.com/$REPO"
    mkdir -p "$TMP/src"
    tar -xzf "$TMP/src.tar.gz" -C "$TMP/src" --strip-components=1
    SRC="$TMP/src"
  fi
}

install_app() {
  # stop a running copy so the new code is what starts
  if systemd_user_ok && systemctl --user is-active --quiet mania-overlay.service 2>/dev/null; then
    systemctl --user stop mania-overlay.service || true
  elif overlay_running; then
    "$BIN" quit >/dev/null 2>&1 || python3 "$SRC/mania-overlay" quit >/dev/null 2>&1 || true
    sleep 1
  fi
  mkdir -p "$APP_DIR" "$BIN_DIR"
  rm -rf "$APP_DIR/mania_overlay" "$APP_DIR/web"
  cp -r "$SRC/mania_overlay" "$SRC/web" "$APP_DIR/"
  cp "$SRC/mania-overlay" "$APP_DIR/mania-overlay"
  chmod +x "$APP_DIR/mania-overlay"
  find "$APP_DIR/mania_overlay" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  ln -sfn "$APP_DIR/mania-overlay" "$BIN"
  local ver
  ver="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/mania_overlay/__init__.py" 2>/dev/null || true)"
  ok "installed ${ver:+v$ver }to $APP_DIR"
  case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR isn't on your PATH yet. Open a new terminal, or run the overlay as $BIN" ;; esac
}

# Which release file we want: "tosu" = the Linux tosu build, "analyser" = the plugin-only ManiaMapAnalyser zip.
ASSET_FILTER='
def wanted(name, mode):
    n = name.lower()
    if mode == "tosu":
        return "linux" in n and n.endswith((".zip", ".tar.gz", ".tgz", ".tar.xz"))
    return n.startswith("maniamapanalyser") and n.endswith(".zip") and "shell" not in n and "bridge" not in n
'

# Latest release asset: github_asset owner/repo mode -> prints "tag url".
# Tries GitHub's API first; it allows only 60 requests an hour per network without a token,
# so if that fails it reads the normal release web page instead. Set GITHUB_TOKEN to use a token.
# Every failure here is handled with || so the ERR trap doesn't fire inside the subshell.
github_asset() {
  local repo="$1" mode="$2" json out final tag html
  local auth=()
  [[ -n ${GITHUB_TOKEN:-} ]] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")
  if json="$(curl -fsSL "${auth[@]}" -H 'Accept: application/vnd.github+json' \
               "https://api.github.com/repos/$repo/releases/latest" 2>/dev/null)"; then
    if out="$(python3 -c "$ASSET_FILTER"'
import json, sys
rel = json.loads(sys.stdin.read())
for a in rel.get("assets", []):
    if wanted(a.get("name", ""), sys.argv[1]):
        print(rel.get("tag_name", "?"), a["browser_download_url"]); sys.exit(0)
sys.exit(3)
' "$mode" <<<"$json" 2>/dev/null)"; then
      echo "$out"; return 0
    fi
  fi
  # fallback: github.com/<repo>/releases/latest redirects to .../releases/tag/<tag>,
  # and .../releases/expanded_assets/<tag> lists the downloads
  final="$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/$repo/releases/latest" 2>/dev/null)" || return 1
  [[ $final == */releases/tag/* ]] || return 1
  tag="${final##*/releases/tag/}"
  html="$(curl -fsSL "https://github.com/$repo/releases/expanded_assets/$tag" 2>/dev/null)" || return 1
  python3 -c "$ASSET_FILTER"'
import re, sys
mode, tag = sys.argv[1], sys.argv[2]
for href in re.findall(r"href=\"(/[^\"]+/releases/download/[^\"]+)\"", sys.stdin.read()):
    if wanted(href.rsplit("/", 1)[-1], mode):
        print(tag, "https://github.com" + href); sys.exit(0)
sys.exit(3)
' "$mode" "$tag" <<<"$html" 2>/dev/null || return 1
}

# Say why a release lookup failed, for the error message.
github_problem() {
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 "https://github.com/$1/releases/latest" 2>/dev/null || true)"
  case "$code" in
    000|"") echo "this computer couldn't reach github.com (no internet, DNS, or a firewall/VPN blocking it)" ;;
    429|403) echo "GitHub is rate-limiting your network right now; wait a few minutes and run the installer again" ;;
    *) echo "GitHub answered, but the latest release has no file the installer recognises (HTTP $code)" ;;
  esac
}

extract() { # extract archive into dir
  local f="$1" d="$2"
  mkdir -p "$d"
  case "$f" in
    *.zip) unzip -q -o "$f" -d "$d" ;;
    *.tar.gz|*.tgz) tar -xzf "$f" -C "$d" ;;
    *.tar.xz) tar -xJf "$f" -C "$d" ;;
    *) if unzip -tq "$f" >/dev/null 2>&1; then unzip -q -o "$f" -d "$d"; else tar -xf "$f" -C "$d"; fi ;;
  esac
}

detect_osu_path() {
  local c
  for c in "$HOME/.local/share/osu-wine/osu!" "$HOME/.local/share/osu-wine/OSU" "$HOME/.local/share/wineprefixes/osu-wineprefix/drive_c/osu!"; do
    if [[ -f $c/osu!.exe ]]; then echo "$c"; return; fi
  done
}

check_osu() {
  step "osu!"
  local p; p="$(detect_osu_path || true)"
  if [[ -n $p ]]; then ok "found osu! at $p"; OSU_PATH="$p"; return; fi
  if command -v osu-wine >/dev/null; then ok "found osu-wine"; return; fi
  warn "osu! wasn't found in the usual osu-winello location."
  info "If it's installed somewhere else that's fine, the overlay doesn't need to know."
  if ask "Install osu! now with osu-winello (github.com/NelloKudo/osu-winello)?" n; then
    command -v git >/dev/null || sudo dnf install -y git
    tmpdir
    git clone --depth 1 "$OSU_WINELLO_REPO" "$TMP/osu-winello"
    info "Starting the osu-winello installer. Follow its prompts; this one continues afterwards."
    ( cd "$TMP/osu-winello" && chmod +x ./osu-winello.sh && ./osu-winello.sh ) <"$TTY" || warn "osu-winello didn't finish. You can run it again later."
    p="$(detect_osu_path || true)"; [[ -n $p ]] && OSU_PATH="$p"
  fi
}

install_tosu() {
  step "tosu (reads live data from osu!)"
  local def=y
  if [[ -n $OPT_TOSU ]]; then
    [[ $OPT_TOSU == yes ]] || { info "skipped (--no-tosu)"; TOSU_MANAGED="${PREV_TOSU:-no}"; return; }
  elif [[ -x $TOSU_DIR/tosu ]]; then
    info "Updating the tosu copy installed by mania-overlay."
  else
    if pgrep -x tosu >/dev/null 2>&1; then
      warn "tosu is already running on this computer (you probably started it yourself)."
      info "mania-overlay can install its own copy and start it on login instead."
      def=n
    fi
    if ! ask "Install tosu and start it automatically?" "$def"; then
      TOSU_MANAGED=no; info "skipped. Make sure your own tosu is running when you play."; return
    fi
  fi
  tmpdir
  local archive tag url
  if [[ -n $TOSU_ARCHIVE ]]; then
    archive="$TOSU_ARCHIVE"; tag="(local file)"
  else
    local found=""
    found="$(github_asset "$TOSU_REPO" tosu)" || found=""
    [[ -n $found ]] || die "couldn't get the Linux tosu release: $(github_problem "$TOSU_REPO").
       Or download the Linux .zip from https://github.com/$TOSU_REPO/releases/latest yourself and run:
       ./install.sh --tosu-archive ~/Downloads/<the file>.zip"
    read -r tag url <<<"$found"
    info "Downloading tosu $tag…"
    archive="$TMP/${url##*/}"
    curl -fsSL "$url" -o "$archive" || die "download failed: $url"
  fi
  rm -rf "$TMP/tosu-x"; extract "$archive" "$TMP/tosu-x"
  local exe
  exe="$(find "$TMP/tosu-x" -type f -name tosu | head -n1)"
  [[ -n $exe ]] || die "the tosu archive has no 'tosu' program in it"
  if systemd_user_ok; then systemctl --user stop mania-overlay-tosu.service >/dev/null 2>&1 || true; fi
  mkdir -p "$TOSU_DIR"
  # copy the whole folder the binary lives in (some builds ship extra files)
  cp -r "$(dirname "$exe")"/. "$TOSU_DIR/"
  chmod +x "$TOSU_DIR/tosu"
  ok "tosu $tag installed to $TOSU_DIR"

  # tosu reads other processes' memory. Fedora allows that for your own processes by default
  # (ptrace_scope 0); if it's locked down, give the binary the capability instead.
  local scope
  scope="$(cat /proc/sys/kernel/yama/ptrace_scope 2>/dev/null || echo 0)"
  USED_SETCAP=no
  if [[ $scope != 0 ]]; then
    info "Your kernel restricts reading other programs' memory (ptrace_scope=$scope)."
    info "Giving tosu permission to read osu! (sudo setcap cap_sys_ptrace=eip)…"
    sudo setcap cap_sys_ptrace=eip "$TOSU_DIR/tosu" && USED_SETCAP=yes && ok "done"
  fi

  # first-time tosu settings: don't open a browser tab on every login
  local envf="$CONFIG_HOME/tosu/tosu.env"
  if [[ ! -f $envf ]]; then
    mkdir -p "$CONFIG_HOME/tosu"
    {
      echo "OPEN_DASHBOARD_ON_STARTUP=false"
      # tosu's self-update would replace the binary and drop the setcap permission
      [[ $USED_SETCAP == yes ]] && echo "ENABLE_AUTOUPDATE=false"
    } >"$envf"
    ok "created $envf (dashboard won't pop up on login)"
  fi
  TOSU_MANAGED=yes
}

tosu_static_dir() {
  local envf="$CONFIG_HOME/tosu/tosu.env" p=""
  [[ -f $envf ]] && p="$(sed -n 's/^STATIC_FOLDER_PATH=//p' "$envf" | tail -n1 | tr -d '"'"'")"
  if [[ -n $p && $p != ./static && $p != '.\static' ]]; then
    [[ $p == ~* ]] && p="$HOME${p:1}"
    echo "$p"
  else
    echo "$DATA_HOME/tosu/static"
  fi
}

install_analyser() {
  step "ManiaMapAnalyser (MSD and dan panel)"
  STATIC_DIR="$(tosu_static_dir)"
  if [[ $OPT_ANALYSER == no ]]; then info "skipped (--no-analyser)"; ANALYSER_MANAGED="${PREV_ANALYSER:-no}"; return; fi
  # one we installed before is updated without asking
  if [[ ${PREV_ANALYSER:-} != yes ]] && ! ask "Install ManiaMapAnalyser into tosu's counters folder?" y; then
    ANALYSER_MANAGED=no; return
  fi
  tmpdir
  local archive tag url
  if [[ -n $ANALYSER_ARCHIVE ]]; then
    archive="$ANALYSER_ARCHIVE"; tag="(local file)"
  else
    local found=""
    found="$(github_asset "$ANALYSER_REPO" analyser)" || found=""
    [[ -n $found ]] || die "couldn't get ManiaMapAnalyser: $(github_problem "$ANALYSER_REPO").
       Or download the zip without \"shell\" in its name from https://github.com/$ANALYSER_REPO/releases/latest and run:
       ./install.sh --analyser-archive ~/Downloads/<the file>.zip"
    read -r tag url <<<"$found"
    info "Downloading ManiaMapAnalyser $tag…"
    archive="$TMP/${url##*/}"
    curl -fsSL "$url" -o "$archive" || die "download failed: $url"
  fi
  rm -rf "$TMP/mma-x"; extract "$archive" "$TMP/mma-x"
  # find the counter folder (the one with index.html + metadata.txt), however the zip nests or names it
  local found
  found="$(python3 -c '
import os, sys
best = None
for root, dirs, files in os.walk(sys.argv[1]):
    if "index.html" in files and "metadata.txt" in files:
        if best is None or root.count(os.sep) < best.count(os.sep):
            best = root
print(best or "")
' "$TMP/mma-x")"
  [[ -n $found ]] || die "the ManiaMapAnalyser zip doesn't contain a counter (index.html + metadata.txt)"
  mkdir -p "$STATIC_DIR"
  rm -rf "${STATIC_DIR:?}/$ANALYSER_DIRNAME"
  cp -r "$found" "$STATIC_DIR/$ANALYSER_DIRNAME"
  ok "ManiaMapAnalyser $tag installed to $STATIC_DIR/$ANALYSER_DIRNAME"
  info "Its settings (MSD version, theme…) are in the tosu dashboard: http://127.0.0.1:24050"
  info "It sends anonymous usage stats by default; turn that off there under Network if you like."
  ANALYSER_MANAGED=yes
}

# ----------------------------------------------------------------------------- autostart
write_units() {
  mkdir -p "$UNIT_DIR"
  if [[ $TOSU_MANAGED == yes ]]; then
    {
      echo "[Unit]"
      echo "Description=tosu (osu! memory reader) for mania-overlay"
      echo "PartOf=graphical-session.target"
      echo "After=graphical-session.target"
      echo
      echo "[Service]"
      echo "WorkingDirectory=%h/.local/share/mania-overlay/tosu"
      echo "ExecStart=%h/.local/share/mania-overlay/tosu/tosu"
      [[ -n ${OSU_PATH:-} ]] && echo "Environment=\"TOSU_OSU_PATH=$OSU_PATH\""
      echo "Restart=on-failure"
      echo "RestartSec=5"
      echo
      echo "[Install]"
      echo "WantedBy=graphical-session.target"
    } >"$UNIT_DIR/mania-overlay-tosu.service"
  fi
  cat >"$UNIT_DIR/mania-overlay.service" <<'EOF'
[Unit]
Description=mania-overlay (osu!mania in-game overlay)
PartOf=graphical-session.target
After=graphical-session.target mania-overlay-tosu.service

[Service]
ExecStart=%h/.local/bin/mania-overlay run
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF
}

write_xdg_autostart() {
  mkdir -p "$AUTOSTART_DIR"
  cat >"$AUTOSTART_DIR/mania-overlay.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=mania-overlay
Comment=osu!mania in-game overlay
Exec=$BIN run
X-GNOME-Autostart-enabled=true
NoDisplay=true
EOF
  if [[ $TOSU_MANAGED == yes ]]; then
    cat >"$AUTOSTART_DIR/mania-overlay-tosu.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=tosu (for mania-overlay)
Comment=Reads live data from osu!
Exec=${OSU_PATH:+env "TOSU_OSU_PATH=$OSU_PATH" }$TOSU_DIR/tosu
Path=$TOSU_DIR
NoDisplay=true
EOF
  fi
}

setup_autostart() {
  step "Start on login"
  AUTOSTART=none
  if [[ $OPT_AUTOSTART == no ]]; then info "skipped (--no-autostart)"; return; fi
  local what="mania-overlay"
  [[ $TOSU_MANAGED == yes ]] && what="mania-overlay and tosu"
  if ! ask "Start $what automatically when you log in?" y; then
    info "OK. Start it yourself with: mania-overlay"; return
  fi
  rm -f "$AUTOSTART_DIR/mania-overlay.desktop" "$AUTOSTART_DIR/mania-overlay-tosu.desktop"
  # Plasma and niri-session both start graphical-session.target, which our units hang off.
  local use_systemd=no
  if systemd_user_ok; then
    if [[ $DESKTOP == niri ]] && in_graphical_session && ! systemctl --user is-active --quiet niri.service 2>/dev/null; then
      use_systemd=no   # niri started without niri-session: graphical-session.target never starts
    else
      use_systemd=yes
    fi
  fi
  if [[ $use_systemd == yes ]]; then
    write_units
    systemctl --user daemon-reload
    local units=(mania-overlay.service)
    [[ $TOSU_MANAGED == yes ]] && units=(mania-overlay-tosu.service "${units[@]}")
    systemctl --user enable "${units[@]}" >/dev/null 2>&1
    AUTOSTART=systemd
    ok "enabled systemd user services: ${units[*]}"
    info "Logs: journalctl --user -u mania-overlay -u mania-overlay-tosu"
  elif [[ $DESKTOP == niri ]]; then
    AUTOSTART=niri   # spawn-at-startup lines go into mania-overlay.kdl below
    ok "niri will start it (spawn-at-startup in mania-overlay.kdl)"
  else
    write_xdg_autostart
    AUTOSTART=xdg
    ok "added to ~/.config/autostart (System Settings → Autostart)"
  fi
}

start_now() {
  in_graphical_session || { info "Not in a graphical session right now; everything starts at your next login."; return; }
  if [[ $AUTOSTART == systemd ]]; then
    systemctl --user import-environment WAYLAND_DISPLAY XDG_CURRENT_DESKTOP >/dev/null 2>&1 || true
    [[ $TOSU_MANAGED == yes ]] && { pkill -x tosu >/dev/null 2>&1 || true; systemctl --user restart mania-overlay-tosu.service || warn "tosu didn't start: journalctl --user -u mania-overlay-tosu"; }
    systemctl --user restart mania-overlay.service || warn "the overlay didn't start: journalctl --user -u mania-overlay"
  else
    if [[ $TOSU_MANAGED == yes ]] && ! pgrep -x tosu >/dev/null 2>&1; then
      (cd "$TOSU_DIR" && TOSU_OSU_PATH="${OSU_PATH:-}" setsid -f ./tosu >/dev/null 2>&1 </dev/null) || true
    fi
    overlay_running || setsid -f "$BIN" run >/dev/null 2>&1 </dev/null || true
  fi
  sleep 2
  if overlay_running; then ok "the overlay is running"; else warn "the overlay isn't answering yet. Run 'mania-overlay' in a terminal to see why."; fi
}

# ----------------------------------------------------------------------------- shortcuts
setup_kde_shortcuts() {
  step "Shortcuts (KDE Plasma)"
  mkdir -p "$(dirname "$DESKTOP_FILE")"
  local actions="" entry id args kde _niri desc
  for entry in "${SHORTCUTS[@]}"; do IFS='|' read -r id args kde _niri desc <<<"$entry"; actions+="$id;"; done
  {
    echo "[Desktop Entry]"
    echo "Type=Application"
    echo "Name=mania-overlay"
    echo "GenericName=osu!mania overlay"
    echo "Comment=In-game overlay for osu!mania: judgements, pp, UR, MSD/dan and a rate changer"
    echo "Exec=$BIN run"
    echo "Icon=input-gaming"
    echo "Terminal=false"
    echo "StartupNotify=false"
    echo "Categories=Game;"
    echo "Actions=$actions"
    for entry in "${SHORTCUTS[@]}"; do
      IFS='|' read -r id args kde _niri desc <<<"$entry"
      echo
      echo "[Desktop Action $id]"
      echo "Name=$desc"
      echo "Exec=$BIN $args"
      echo "X-KDE-Shortcuts=$kde"
    done
  } >"$DESKTOP_FILE"
  mkdir -p "$(dirname "$KGLOBALACCEL_FILE")"
  cp "$DESKTOP_FILE" "$KGLOBALACCEL_FILE"
  # KDE's shortcut daemon (kglobalaccel) reads X-KDE-Shortcuts from app files. Plasma 6.1+
  # picks up new ones as soon as the app database is rebuilt; older versions at next login.
  if command -v kbuildsycoca6 >/dev/null; then
    kbuildsycoca6 >/dev/null 2>&1 || true
  elif command -v kbuildsycoca5 >/dev/null; then
    kbuildsycoca5 >/dev/null 2>&1 || true
  fi
  ok "registered with KDE (and added mania-overlay to the app menu)"
  for entry in "${SHORTCUTS[@]}"; do
    IFS='|' read -r id args kde _niri desc <<<"$entry"
    printf '      %-12s %s\n' "$kde" "$desc"
  done
  info "Change them in System Settings → Keyboard → Shortcuts → mania-overlay."
  info "If a key does nothing, it may already be taken; pick another there. A log out and in also helps."
}

write_niri_include() {
  mkdir -p "$NIRI_DIR"
  local entry id args _kde niri desc
  {
    echo "// mania-overlay shortcuts. Written by mania-overlay's install.sh, which"
    echo "// overwrites this file when you re-run it. To change a key, edit it here"
    echo "// and keep a copy, or add your own bind for the same command in config.kdl."
    echo "//"
    echo "// allow-inhibiting=false keeps the keys working while fullscreen osu! has focus."
    echo
    if [[ $AUTOSTART == niri ]]; then
      [[ $TOSU_MANAGED == yes ]] && echo "spawn-sh-at-startup \"cd ~/.local/share/mania-overlay/tosu && ${OSU_PATH:+TOSU_OSU_PATH='$OSU_PATH' }exec ./tosu\""
      echo "spawn-sh-at-startup \"~/.local/bin/mania-overlay run\""
      echo
    fi
    echo "binds {"
    for entry in "${SHORTCUTS[@]}"; do
      IFS='|' read -r id args _kde niri desc <<<"$entry"
      printf '    %s allow-inhibiting=false hotkey-overlay-title="mania-overlay: %s" { spawn-sh "~/.local/bin/mania-overlay %s"; }\n' "$niri" "$desc" "$args"
    done
    echo "}"
  } >"$NIRI_INCLUDE_FILE"
}

setup_niri_shortcuts() {
  step "Shortcuts (niri)"
  write_niri_include
  ok "wrote $NIRI_INCLUDE_FILE"
  local cfg; cfg="$(niri_config)"
  if ! niri_supports_include; then
    warn "your niri is older than 25.11 (or wasn't found), so it can't include other files."
    info "Paste the contents of $NIRI_INCLUDE_FILE at the bottom of $cfg yourself."
    return
  fi
  if [[ ! -f $cfg ]]; then
    warn "$cfg doesn't exist yet (niri creates it on first start)."
    info "Start niri once, then rerun this installer, or add this line to it: include \"mania-overlay.kdl\""
    return
  fi
  local errf; tmpdir; errf="$TMP/niri-validate.txt"
  local backup=""
  if ! grep -q '^include "mania-overlay.kdl"' "$cfg"; then
    backup="$cfg.mania-backup-$(date +%Y%m%d-%H%M%S)"
    cp "$cfg" "$backup"
    printf '\n// Added by mania-overlay (remove both lines to drop its shortcuts)\ninclude "mania-overlay.kdl"\n' >>"$cfg"
    if niri_validate "$errf"; then
      ok "added include \"mania-overlay.kdl\" to the end of config.kdl (backup: ${backup##*/})"
    else
      cp "$backup" "$cfg"
      warn "niri rejected the config with the include line, so I put your config.kdl back unchanged:"
      sed 's/^/        /' "$errf" | head -n 20
      info "Fix the error above (it may be unrelated), then rerun the installer."
      return
    fi
  else
    if niri_validate "$errf"; then ok "config.kdl already includes mania-overlay.kdl"; else
      warn "niri reports a config error:"; sed 's/^/        /' "$errf" | head -n 20
    fi
  fi
  tidy_old_niri_lines "$cfg"
  for entry in "${SHORTCUTS[@]}"; do
    IFS='|' read -r id args _kde niri desc <<<"$entry"
    printf '      %-12s %s\n' "$niri" "$desc"
  done
  info "niri reloads its config by itself; the keys work right away."
}

# Comment out one-line mania-overlay binds / spawn lines that people added by hand
# before the installer existed. Only complete single-line entries are touched.
tidy_old_niri_lines() {
  local cfg="$1" lines pattern
  # complete one-line binds that run mania-overlay
  pattern='[^/[:space:]][^{]*\{[[:space:]]*spawn(-sh)?[[:space:]][^}]*mania-overlay[^}]*\}[[:space:]]*'
  # startup lines only when the installer now starts it (otherwise they're the user's only autostart)
  [[ $AUTOSTART != none ]] && pattern="spawn(-sh)?-at-startup[[:space:]].*mania-overlay.*|$pattern"
  lines="$(grep -nE "^[[:space:]]*($pattern)\$" "$cfg" || true)"
  [[ -n $lines ]] || return 0
  warn "config.kdl still has mania-overlay lines from a manual setup:"
  sed 's/^/        /' <<<"$lines"
  info "They're no longer needed (mania-overlay.kdl now has the shortcuts$([[ $AUTOSTART == none ]] || echo ' and autostart is set up'))."
  if ask "Comment them out? (a backup of config.kdl is made first)" y; then
    local backup errf="$TMP/niri-validate2.txt"
    backup="$cfg.mania-backup-$(date +%Y%m%d-%H%M%S)-tidy"
    cp "$cfg" "$backup"
    local n
    while IFS=: read -r n _; do
      sed -i "${n}s|^\\([[:space:]]*\\)|\\1// (mania-overlay installer) |" "$cfg"
    done <<<"$lines"
    if niri_validate "$errf"; then ok "commented them out"; else
      cp "$backup" "$cfg"; warn "niri didn't like that, so config.kdl was restored. Remove those lines yourself."
    fi
  fi
}

save_state() {
  mkdir -p "$APP_DIR"
  cat >"$STATE_FILE" <<EOF
# written by install.sh; used when you re-run it or uninstall
DESKTOP=$DESKTOP
TOSU_MANAGED=${TOSU_MANAGED:-no}
ANALYSER_MANAGED=${ANALYSER_MANAGED:-no}
AUTOSTART=${AUTOSTART:-none}
STATIC_DIR=${STATIC_DIR:-}
EOF
}

summary() {
  local k1 k2
  if [[ $DESKTOP == kde ]]; then k1="Meta+Alt+O"; k2="Meta+Alt+R"; else k1="Mod+Alt+O"; k2="Mod+Alt+R"; fi
  printf '\n%sAll done.%s\n\n' "$C_G$C_B" "$C_0"
  cat <<EOF
  • Start osu!. The overlay shows up when tosu sees the game.
  • $k1  opens the editor: drag widgets, pick the monitor (General tab), colours.
  • $k2  opens the rate changer: any rate from 0.5x to 2x, and OD.
  • Commands: mania-overlay edit | rate-menu | toggle | rate 1.1 --od 8 | quit
  • Settings: ~/.config/mania-overlay/settings.json
  • Re-run this installer to update. Uninstall: install.sh --uninstall
EOF
}

main() {
  if [[ $OPT_UNINSTALL == 1 ]]; then uninstall; exit 0; fi
  printf '%smania-overlay installer%s — Fedora · KDE Plasma / niri\n' "$C_B" "$C_0"
  self_update
  load_state
  check_system
  choose_desktop
  install_packages
  get_source
  install_app
  OSU_PATH=""
  check_osu
  TOSU_MANAGED="${PREV_TOSU:-no}"; ANALYSER_MANAGED="${PREV_ANALYSER:-no}"
  [[ ${PREV_TOSU:-} == yes && -z $OPT_TOSU ]] && OPT_TOSU=yes
  install_tosu
  install_analyser
  setup_autostart
  if [[ $DESKTOP == kde ]]; then
    setup_kde_shortcuts
  else
    setup_niri_shortcuts
  fi
  save_state
  step "Starting"
  start_now
  summary
}

main "$@"
