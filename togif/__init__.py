"""TOgif - a configurable video-to-GIF converter.

The package exposes the conversion engine (:mod:`togif.converter`), a
command-line interface (:mod:`togif.cli`) and a Tkinter GUI
(:mod:`togif.gui`).
"""

from .converter import (
    ConversionSettings,
    Converter,
    FFmpegNotFoundError,
    TimeRange,
    compute_keep_ranges,
    find_ffmpeg,
    parse_time,
)

__all__ = [
    "ConversionSettings",
    "Converter",
    "FFmpegNotFoundError",
    "TimeRange",
    "compute_keep_ranges",
    "find_ffmpeg",
    "parse_time",
]

__version__ = "1.0.0"
