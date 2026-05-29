"""Core video-to-GIF conversion engine.

This module is intentionally free of any GUI dependency so that it can be
reused from the command line, the GUI, or other Python code, and so that the
command-building logic can be unit tested without a real ``ffmpeg`` binary.

The conversion is built on top of ``ffmpeg`` and uses the standard two-pass
palette technique (``palettegen`` + ``paletteuse``) to produce high quality
GIFs. Frame rate, output size, quality and the time range (including removing
one or more segments from the middle of the video) are all configurable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


class FFmpegNotFoundError(RuntimeError):
    """Raised when no usable ``ffmpeg`` executable can be located."""


class ConversionError(RuntimeError):
    """Raised when an ``ffmpeg`` invocation fails."""


# Mapping of friendly quality names to the ffmpeg palette parameters that
# control the visual fidelity of the resulting GIF.
QUALITY_PRESETS = {
    "high": {"max_colors": 256, "stats_mode": "diff", "dither": "sierra2_4a"},
    "medium": {"max_colors": 192, "stats_mode": "diff", "dither": "bayer:bayer_scale=3"},
    "low": {"max_colors": 128, "stats_mode": "full", "dither": "none"},
}

DEFAULT_QUALITY = "high"
DEFAULT_FPS = 15


def find_ffmpeg(explicit_path: Optional[str] = None) -> str:
    """Locate an ``ffmpeg`` executable.

    Resolution order:

    1. ``explicit_path`` if provided and runnable.
    2. The ``imageio-ffmpeg`` bundled binary (handy on Windows where ffmpeg is
       frequently not installed system-wide), if that package is available.
    3. ``ffmpeg`` found on the system ``PATH``.

    Raises :class:`FFmpegNotFoundError` if none can be found.
    """

    if explicit_path:
        if os.path.isfile(explicit_path) or shutil.which(explicit_path):
            return explicit_path
        raise FFmpegNotFoundError(f"ffmpeg not found at: {explicit_path}")

    try:  # pragma: no cover - depends on optional dependency being installed
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - any failure means fall through to PATH
        pass

    found = shutil.which("ffmpeg")
    if found:
        return found

    raise FFmpegNotFoundError(
        "Could not find ffmpeg. Install it and add it to your PATH, or "
        "install the optional 'imageio-ffmpeg' package."
    )


def parse_time(value) -> float:
    """Parse a time value into seconds.

    Accepts plain seconds (``"12"``, ``12``, ``12.5``) or the colon notations
    ``"MM:SS"`` / ``"HH:MM:SS"`` with optional fractional seconds.
    """

    if value is None or value == "":
        raise ValueError("empty time value")
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise ValueError("time value cannot be negative")
        return seconds

    text = str(value).strip()
    if not text:
        raise ValueError("empty time value")

    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid time format: {value!r}")
    try:
        numbers = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"invalid time format: {value!r}") from exc

    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    if seconds < 0:
        raise ValueError("time value cannot be negative")
    return seconds


@dataclass
class TimeRange:
    """A half-open time range expressed in seconds.

    ``end`` may be ``None`` to mean "until the end of the video".
    """

    start: float
    end: Optional[float] = None

    def __post_init__(self) -> None:
        self.start = float(self.start)
        if self.start < 0:
            raise ValueError("start must be >= 0")
        if self.end is not None:
            self.end = float(self.end)
            if self.end <= self.start:
                raise ValueError("end must be greater than start")


def compute_keep_ranges(
    trim_start: Optional[float],
    trim_end: Optional[float],
    remove_segments: Sequence[TimeRange],
) -> List[Tuple[float, Optional[float]]]:
    """Compute the list of ranges to keep.

    Given an overall trim window (``trim_start`` .. ``trim_end``) and a list of
    segments to remove from within that window, return the complementary list
    of ``(start, end)`` ranges to keep. ``end`` is ``None`` for an open-ended
    final range (used when ``trim_end`` is unknown).
    """

    start = float(trim_start) if trim_start else 0.0
    if start < 0:
        raise ValueError("trim_start must be >= 0")
    if trim_end is not None:
        trim_end = float(trim_end)
        if trim_end <= start:
            raise ValueError("trim_end must be greater than trim_start")

    # Clamp and sort the removal segments to the trim window.
    segments = sorted(remove_segments, key=lambda r: r.start)

    ranges: List[Tuple[float, Optional[float]]] = []
    cursor = start
    for seg in segments:
        seg_start = max(seg.start, start)
        seg_end = seg.end
        if trim_end is not None:
            seg_start = min(seg_start, trim_end)
            seg_end = trim_end if seg_end is None else min(seg_end, trim_end)
        if seg_end is None:
            # Removal runs to the (unknown) end: nothing after it survives.
            if seg_start > cursor:
                ranges.append((cursor, seg_start))
            return ranges
        if seg_start > cursor:
            ranges.append((cursor, seg_start))
        cursor = max(cursor, seg_end)

    if trim_end is None:
        ranges.append((cursor, None))
    elif cursor < trim_end:
        ranges.append((cursor, trim_end))

    return ranges


def _format_number(value: float) -> str:
    """Format a float for an ffmpeg expression without trailing zeros."""

    text = ("%f" % value).rstrip("0").rstrip(".")
    return text if text else "0"


def build_select_expression(
    keep_ranges: Sequence[Tuple[float, Optional[float]]]
) -> Optional[str]:
    """Build an ffmpeg ``select`` expression for the given keep ranges.

    Returns ``None`` when the ranges cover the whole video (a single
    open-ended range starting at 0), meaning no time filtering is required.
    """

    if not keep_ranges:
        raise ValueError("no ranges to keep - the whole video was removed")

    if len(keep_ranges) == 1:
        start, end = keep_ranges[0]
        if start <= 0 and end is None:
            return None

    parts = []
    for start, end in keep_ranges:
        if end is None:
            parts.append(f"gte(t,{_format_number(start)})")
        else:
            parts.append(
                f"between(t,{_format_number(start)},{_format_number(end)})"
            )
    return "+".join(parts)


@dataclass
class ConversionSettings:
    """All options controlling a single conversion."""

    input_path: str
    output_path: str
    fps: int = DEFAULT_FPS
    width: Optional[int] = None
    height: Optional[int] = None
    quality: str = DEFAULT_QUALITY
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None
    remove_segments: List[TimeRange] = field(default_factory=list)
    loop: int = 0  # 0 = loop forever, -1 = no loop, n = repeat n times

    def validate(self) -> None:
        if self.fps <= 0:
            raise ValueError("fps must be a positive integer")
        if self.quality not in QUALITY_PRESETS:
            raise ValueError(
                f"unknown quality {self.quality!r}; choose from "
                f"{', '.join(QUALITY_PRESETS)}"
            )
        if self.width is not None and self.width <= 0:
            raise ValueError("width must be a positive integer")
        if self.height is not None and self.height <= 0:
            raise ValueError("height must be a positive integer")
        if self.trim_start is not None and self.trim_start < 0:
            raise ValueError("trim_start must be >= 0")
        if (
            self.trim_start is not None
            and self.trim_end is not None
            and self.trim_end <= self.trim_start
        ):
            raise ValueError("trim_end must be greater than trim_start")

    def scale_expression(self) -> Optional[str]:
        """Build the ffmpeg ``scale`` argument, or ``None`` to keep size."""

        if self.width is None and self.height is None:
            return None
        # -2 keeps the aspect ratio while forcing an even dimension.
        width = self.width if self.width is not None else -2
        height = self.height if self.height is not None else -2
        return f"scale={width}:{height}:flags=lanczos"

    def keep_ranges(self) -> List[Tuple[float, Optional[float]]]:
        return compute_keep_ranges(
            self.trim_start, self.trim_end, self.remove_segments
        )

    def common_filter(self) -> str:
        """Build the filter chain shared by both ffmpeg passes."""

        filters = [f"fps={self.fps}"]
        select_expr = build_select_expression(self.keep_ranges())
        if select_expr is not None:
            filters.append(f"select='{select_expr}'")
            filters.append(f"setpts=N/{self.fps}/TB")
        scale = self.scale_expression()
        if scale is not None:
            filters.append(scale)
        return ",".join(filters)


class Converter:
    """Drives ``ffmpeg`` to perform the conversion."""

    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = find_ffmpeg(ffmpeg_path)

    def build_palettegen_command(
        self, settings: ConversionSettings, palette_path: str
    ) -> List[str]:
        settings.validate()
        preset = QUALITY_PRESETS[settings.quality]
        vf = (
            f"{settings.common_filter()},"
            f"palettegen=max_colors={preset['max_colors']}:"
            f"stats_mode={preset['stats_mode']}"
        )
        return [
            self.ffmpeg_path,
            "-y",
            "-i",
            settings.input_path,
            "-vf",
            vf,
            palette_path,
        ]

    def build_paletteuse_command(
        self, settings: ConversionSettings, palette_path: str
    ) -> List[str]:
        settings.validate()
        preset = QUALITY_PRESETS[settings.quality]
        filter_complex = (
            f"[0:v]{settings.common_filter()}[x];"
            f"[x][1:v]paletteuse=dither={preset['dither']}"
        )
        return [
            self.ffmpeg_path,
            "-y",
            "-i",
            settings.input_path,
            "-i",
            palette_path,
            "-lavfi",
            filter_complex,
            "-loop",
            str(settings.loop),
            settings.output_path,
        ]

    def convert(
        self,
        settings: ConversionSettings,
        progress_callback=None,
    ) -> str:
        """Run the two-pass conversion and return the output path.

        ``progress_callback`` is an optional callable invoked with short status
        strings so callers (e.g. the GUI) can surface progress to the user.
        """

        settings.validate()
        if not os.path.isfile(settings.input_path):
            raise FileNotFoundError(settings.input_path)

        out_dir = os.path.dirname(os.path.abspath(settings.output_path))
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        def report(message: str) -> None:
            if progress_callback is not None:
                progress_callback(message)

        palette_fd, palette_path = tempfile.mkstemp(suffix=".png", prefix="togif_palette_")
        os.close(palette_fd)
        try:
            report("Generating colour palette...")
            self._run(self.build_palettegen_command(settings, palette_path))
            report("Encoding GIF...")
            self._run(self.build_paletteuse_command(settings, palette_path))
        finally:
            try:
                os.remove(palette_path)
            except OSError:
                pass

        report("Done.")
        return settings.output_path

    def _run(self, command: Sequence[str]) -> None:
        result = subprocess.run(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise ConversionError(
                f"ffmpeg failed (exit code {result.returncode}):\n{stderr}"
            )
