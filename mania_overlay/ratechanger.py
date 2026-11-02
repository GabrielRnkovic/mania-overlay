"""Create rate-changed and/or OD-changed copies of osu! beatmaps.

Rate: every timestamp in the .osu is divided by the rate, uninherited beat
lengths are divided by the rate (so BPM is multiplied), and the audio is sped
up with ffmpeg — either keeping pitch (atempo / rubberband) or nightcore-style.

OD: the [Difficulty] OverallDifficulty value is replaced. An OD-only copy
(rate 1.0) keeps the original timing and audio file.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MIN_RATE, MAX_RATE = 0.5, 3.0
MIN_OD, MAX_OD = 0.0, 10.0
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class RateError(Exception):
    pass


@dataclass
class RateResult:
    rate: float
    osu_path: Path
    audio_path: Path
    version: str
    skipped: bool = False
    od: float | None = None

    def to_dict(self) -> dict:
        return {
            "rate": self.rate,
            "od": self.od,
            "osu": str(self.osu_path),
            "audio": str(self.audio_path),
            "version": self.version,
            "skipped": self.skipped,
        }


def fmt_rate(rate: float) -> str:
    return f"{rate:.2f}".rstrip("0").rstrip(".")


def fmt_od(od: float) -> str:
    return f"{od:.1f}".rstrip("0").rstrip(".")


def is_one(rate: float) -> bool:
    return abs(rate - 1.0) < 1e-6


def _num(value: float) -> str:
    """Format a number the way .osu files expect (ints where possible)."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.12g}"


def _t(value: str, rate: float) -> str:
    return str(int(round(float(value) / rate)))


# --------------------------------------------------------------------------- .osu


def read_osu(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="surrogateescape")


def osu_field(text: str, section: str, key: str) -> str | None:
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        elif current == section and ":" in line:
            k, v = line.split(":", 1)
            if k.strip() == key:
                return v.strip()
    return None


def transform_osu(text: str, rate: float, version: str, audio_name: str, od: float | None = None) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    retime = not is_one(rate)
    out: list[str] = []
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.append(raw)
            continue
        if not line or line.startswith("//"):
            out.append(raw)
            continue
        if section == "Difficulty" and od is not None and line.split(":", 1)[0].strip() == "OverallDifficulty":
            out.append(f"OverallDifficulty:{_num(od)}")
            continue
        if not retime and section in ("Editor", "Events", "TimingPoints", "HitObjects"):
            out.append(raw)  # OD-only copy: keep every timestamp exactly as it was
            continue
        try:
            out.append(_transform_line(section, raw, line, rate, version, audio_name))
        except (ValueError, IndexError):
            out.append(raw)  # leave anything we can't parse untouched
    return newline.join(out) + newline


def _transform_line(section, raw, line, rate, version, audio_name) -> str:
    if section in ("General", "Metadata", "Editor") and ":" in line:
        key, value = (s.strip() for s in line.split(":", 1))
        if section == "General":
            if key == "AudioFilename":
                return f"AudioFilename: {audio_name}"
            if key == "PreviewTime" and value != "-1":
                return f"PreviewTime: {_t(value, rate)}" if not is_one(rate) else raw
        elif section == "Metadata":
            if key == "Version":
                return f"Version:{version}"
            if key == "BeatmapID":
                return "BeatmapID:0"
            if key == "Tags":
                return "Tags:" + (value + " " if value else "") + "rate_change"
        elif section == "Editor" and key == "Bookmarks" and value:
            return "Bookmarks: " + ",".join(_t(v, rate) for v in value.split(","))
        return raw

    if section == "TimingPoints":
        parts = line.split(",")
        parts[0] = _t(parts[0], rate)
        beat_length = float(parts[1])
        if beat_length > 0:  # uninherited: ms per beat; inherited (<0) is an SV multiplier
            parts[1] = _num(beat_length / rate)
        return ",".join(parts)

    if section == "HitObjects":
        parts = line.split(",")
        parts[2] = _t(parts[2], rate)
        obj_type = int(parts[3])
        if obj_type & 128 and len(parts) > 5:  # mania hold note: endTime:hitSample
            end, sep, rest = parts[5].partition(":")
            parts[5] = _t(end, rate) + sep + rest
        elif obj_type & 8 and len(parts) > 5:  # spinner
            parts[5] = _t(parts[5], rate)
        return ",".join(parts)

    if section == "Events":
        parts = line.split(",")
        kind = parts[0]
        if kind in ("2", "Break"):
            parts[1], parts[2] = _t(parts[1], rate), _t(parts[2], rate)
        elif kind in ("1", "Video", "5", "Sample"):
            parts[1] = _t(parts[1], rate)
        return ",".join(parts)

    return raw


def safe_name(name: str) -> str:
    return _ILLEGAL.sub("", name).strip()


def rated_osu_name(original: Path, new_version: str) -> str:
    stem = original.name
    m = re.match(r"^(.*)\[[^\]]*\]\.osu$", stem, re.IGNORECASE)
    base = m.group(1) if m else stem[: -len(".osu")] + " "
    return safe_name(f"{base}[{new_version}]") + ".osu"


# --------------------------------------------------------------------------- audio


def ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RateError("ffmpeg not found. Install it with: sudo dnf install ffmpeg-free")
    return path


def _ffmpeg_has(kind: str, name: str) -> bool:
    try:
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", f"-{kind}"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError, RateError):
        return False
    return re.search(rf"\s{re.escape(name)}\s", out) is not None


def sample_rate(src: Path) -> int:
    probe = shutil.which("ffprobe")
    if probe:
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-select_streams", "a:0", "-show_entries",
                 "stream=sample_rate", "-of", "default=nw=1:nk=1", str(src)],
                capture_output=True, text=True, timeout=20).stdout.strip()
            if out.isdigit():
                return int(out)
        except (OSError, subprocess.SubprocessError):
            pass
    return 44100


def _atempo_chain(rate: float) -> str:
    # atempo accepts 0.5..2.0 (older ffmpeg); chain filters for anything outside that
    filters, r = [], rate
    while r > 2.0:
        filters.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        filters.append("atempo=0.5")
        r /= 0.5
    filters.append(f"atempo={r:.6f}")
    return ",".join(filters)


def audio_filter(src: Path, rate: float, pitch: bool) -> str:
    if pitch:
        sr = sample_rate(src)
        return f"asetrate={int(round(sr * rate))},aresample={sr}"
    if _ffmpeg_has("filters", "rubberband"):
        return f"rubberband=tempo={rate:.6f}"
    return _atempo_chain(rate)


def audio_codec(fmt: str) -> tuple[str, list[str]]:
    if fmt == "mp3" and _ffmpeg_has("encoders", "libmp3lame"):
        return ".mp3", ["-c:a", "libmp3lame", "-q:a", "0"]
    return ".ogg", ["-c:a", "libvorbis", "-q:a", "7"]


def convert_audio(src: Path, dst: Path, rate: float, pitch: bool, codec_args: list[str]) -> None:
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    cmd = [ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
           "-vn", "-map_metadata", "-1", "-filter:a", audio_filter(src, rate, pitch),
           *codec_args, str(tmp)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RateError(f"ffmpeg failed: {proc.stderr.strip()[-400:]}")
    tmp.replace(dst)


# --------------------------------------------------------------------------- main entry


def make_rate(osu_path: Path, rate: float, pitch: bool = False, overwrite: bool = False,
              audio_format: str = "ogg", od: float | None = None) -> RateResult:
    """Write a copy of the map at `rate` (and with OD `od`, if given) next to the original."""
    rate = round(float(rate), 3)
    if not MIN_RATE <= rate <= MAX_RATE:
        raise RateError(f"rate must be between {MIN_RATE} and {MAX_RATE}")
    if od is not None:
        od = round(float(od), 1)
        if not MIN_OD <= od <= MAX_OD:
            raise RateError(f"OD must be between {fmt_od(MIN_OD)} and {fmt_od(MAX_OD)}")
    if is_one(rate) and od is None:
        raise RateError("rate 1.0x without an OD change is the original map")
    osu_path = Path(osu_path)
    if not osu_path.is_file():
        raise RateError(f"beatmap not found: {osu_path}")

    text = read_osu(osu_path)
    mode = osu_field(text, "General", "Mode")
    if mode is not None and mode.strip() != "3":
        raise RateError("this isn't an osu!mania map (converts aren't supported)")
    audio_name = osu_field(text, "General", "AudioFilename")
    if not audio_name:
        raise RateError("map has no AudioFilename")
    folder = osu_path.parent
    audio_src = folder / audio_name
    if not audio_src.is_file():
        raise RateError(f"audio file missing: {audio_src}")

    if od is not None:
        current = osu_field(text, "Difficulty", "OverallDifficulty")
        try:
            if current is not None and is_one(rate) and abs(float(current) - od) < 1e-6:
                raise RateError(f"this map is already OD{fmt_od(od)}")
        except ValueError:
            pass

    version = new_version(osu_field(text, "Metadata", "Version") or "Normal", rate, pitch, od)
    osu_dst = folder / rated_osu_name(osu_path, version)
    if is_one(rate):
        audio_dst = audio_src  # OD-only: same audio, same timing
    else:
        ext, codec_args = audio_codec(audio_format)
        audio_dst = folder / safe_name(f"{Path(audio_name).stem}_{fmt_rate(rate)}x{'_p' if pitch else ''}{ext}")

    if osu_dst.exists() and not overwrite:
        return RateResult(rate, osu_dst, audio_dst, version, skipped=True, od=od)
    # Several difficulties share one audio file, so reuse a converted one if it's there.
    if not is_one(rate) and (overwrite or not audio_dst.exists()):
        convert_audio(audio_src, audio_dst, rate, pitch, codec_args)
    new_text = transform_osu(text, rate, version, audio_name if is_one(rate) else audio_dst.name, od=od)
    osu_dst.write_text(new_text, encoding="utf-8", errors="surrogateescape")
    return RateResult(rate, osu_dst, audio_dst, version, od=od)


def new_version(original: str, rate: float, pitch: bool, od: float | None) -> str:
    """Difficulty name for the copy, e.g. "Insane 1.1x", "Insane 1.1x (pitch) OD8", "Insane OD7.5"."""
    parts = [original]
    if not is_one(rate):
        parts.append(f"{fmt_rate(rate)}x" + (" (pitch)" if pitch else ""))
    if od is not None:
        parts.append(f"OD{fmt_od(od)}")
    return " ".join(parts)
