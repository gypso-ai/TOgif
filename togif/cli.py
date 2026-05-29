"""Command-line interface for TOgif."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .converter import (
    ConversionError,
    ConversionSettings,
    Converter,
    FFmpegNotFoundError,
    QUALITY_PRESETS,
    TimeRange,
    parse_time,
)


def _parse_segment(text: str) -> TimeRange:
    """Parse a ``start-end`` segment string into a :class:`TimeRange`."""

    if "-" not in text:
        raise argparse.ArgumentTypeError(
            f"segment must be in 'start-end' form, got {text!r}"
        )
    start_text, end_text = text.split("-", 1)
    try:
        start = parse_time(start_text)
        end = parse_time(end_text)
        return TimeRange(start=start, end=end)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="togif",
        description="Convert a video to an animated GIF with configurable "
        "frame rate, quality, size and time trimming.",
    )
    parser.add_argument("input", help="Path to the source video file")
    parser.add_argument("output", help="Path to the GIF file to create")
    parser.add_argument(
        "--fps", type=int, default=15, help="Frames per second (default: 15)"
    )
    parser.add_argument(
        "--width", type=int, default=None, help="Output width in pixels"
    )
    parser.add_argument(
        "--height", type=int, default=None, help="Output height in pixels"
    )
    parser.add_argument(
        "--quality",
        choices=sorted(QUALITY_PRESETS),
        default="high",
        help="GIF quality preset (default: high)",
    )
    parser.add_argument(
        "--start",
        type=parse_time,
        default=None,
        help="Trim start time (seconds or HH:MM:SS)",
    )
    parser.add_argument(
        "--end",
        type=parse_time,
        default=None,
        help="Trim end time (seconds or HH:MM:SS)",
    )
    parser.add_argument(
        "--remove",
        type=_parse_segment,
        action="append",
        default=[],
        metavar="START-END",
        help="Remove a time segment (e.g. the middle); repeatable",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="Loop count: 0 = forever (default), -1 = no loop, n = repeat n times",
    )
    parser.add_argument(
        "--ffmpeg",
        default=None,
        help="Path to the ffmpeg executable (auto-detected if omitted)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = ConversionSettings(
        input_path=args.input,
        output_path=args.output,
        fps=args.fps,
        width=args.width,
        height=args.height,
        quality=args.quality,
        trim_start=args.start,
        trim_end=args.end,
        remove_segments=args.remove,
        loop=args.loop,
    )

    try:
        converter = Converter(args.ffmpeg)
        converter.convert(settings, progress_callback=lambda m: print(m))
    except (FFmpegNotFoundError, ConversionError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {settings.output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
