"""Unit tests for the TOgif conversion engine.

These tests exercise the pure command-building / time-range logic and do not
require a real ffmpeg binary to be installed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from togif.converter import (  # noqa: E402
    ConversionSettings,
    Converter,
    TimeRange,
    build_select_expression,
    compute_keep_ranges,
    parse_time,
)


class ParseTimeTests(unittest.TestCase):
    def test_plain_seconds(self):
        self.assertEqual(parse_time("12"), 12.0)
        self.assertEqual(parse_time(12), 12.0)
        self.assertEqual(parse_time(12.5), 12.5)

    def test_mm_ss(self):
        self.assertEqual(parse_time("01:30"), 90.0)

    def test_hh_mm_ss(self):
        self.assertEqual(parse_time("01:00:00"), 3600.0)
        self.assertEqual(parse_time("00:01:30.5"), 90.5)

    def test_invalid(self):
        for bad in ["", "ab", "1:2:3:4", "-5"]:
            with self.assertRaises(ValueError):
                parse_time(bad)


class KeepRangeTests(unittest.TestCase):
    def test_no_trim_no_removal(self):
        ranges = compute_keep_ranges(None, None, [])
        self.assertEqual(ranges, [(0.0, None)])

    def test_trim_only(self):
        ranges = compute_keep_ranges(5, 20, [])
        self.assertEqual(ranges, [(5.0, 20.0)])

    def test_remove_middle(self):
        # Keep 0..30 but cut out the middle 10..20.
        ranges = compute_keep_ranges(0, 30, [TimeRange(10, 20)])
        self.assertEqual(ranges, [(0.0, 10.0), (20.0, 30.0)])

    def test_remove_middle_open_end(self):
        ranges = compute_keep_ranges(None, None, [TimeRange(10, 20)])
        self.assertEqual(ranges, [(0.0, 10.0), (20.0, None)])

    def test_multiple_removals_sorted(self):
        ranges = compute_keep_ranges(
            0, 100, [TimeRange(60, 70), TimeRange(10, 20)]
        )
        self.assertEqual(ranges, [(0.0, 10.0), (20.0, 60.0), (70.0, 100.0)])

    def test_removal_clamped_to_trim(self):
        ranges = compute_keep_ranges(10, 50, [TimeRange(5, 60)])
        self.assertEqual(ranges, [])

    def test_invalid_trim(self):
        with self.assertRaises(ValueError):
            compute_keep_ranges(20, 10, [])


class SelectExpressionTests(unittest.TestCase):
    def test_full_video_returns_none(self):
        self.assertIsNone(build_select_expression([(0.0, None)]))

    def test_single_range(self):
        self.assertEqual(
            build_select_expression([(5.0, 20.0)]), "between(t,5,20)"
        )

    def test_removed_middle(self):
        expr = build_select_expression([(0.0, 10.0), (20.0, None)])
        self.assertEqual(expr, "between(t,0,10)+gte(t,20)")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            build_select_expression([])


class ScaleTests(unittest.TestCase):
    def test_no_size(self):
        s = ConversionSettings("in.mp4", "out.gif")
        self.assertIsNone(s.scale_expression())

    def test_width_only(self):
        s = ConversionSettings("in.mp4", "out.gif", width=320)
        self.assertEqual(s.scale_expression(), "scale=320:-2:flags=lanczos")

    def test_both(self):
        s = ConversionSettings("in.mp4", "out.gif", width=320, height=240)
        self.assertEqual(s.scale_expression(), "scale=320:240:flags=lanczos")


class CommonFilterTests(unittest.TestCase):
    def test_basic_filter(self):
        s = ConversionSettings("in.mp4", "out.gif", fps=10)
        self.assertEqual(s.common_filter(), "fps=10")

    def test_filter_with_trim_and_scale(self):
        s = ConversionSettings(
            "in.mp4", "out.gif", fps=20, width=480, trim_start=5, trim_end=15
        )
        self.assertEqual(
            s.common_filter(),
            "fps=20,select='between(t,5,15)',setpts=N/20/TB,scale=480:-2:flags=lanczos",
        )


class CommandBuildingTests(unittest.TestCase):
    def setUp(self):
        # Use a fake ffmpeg path so we don't need the real binary.
        self.converter = Converter.__new__(Converter)
        self.converter.ffmpeg_path = "ffmpeg"

    def test_validation_rejects_bad_fps(self):
        s = ConversionSettings("in.mp4", "out.gif", fps=0)
        with self.assertRaises(ValueError):
            s.validate()

    def test_validation_rejects_unknown_quality(self):
        s = ConversionSettings("in.mp4", "out.gif", quality="ultra")
        with self.assertRaises(ValueError):
            s.validate()

    def test_palettegen_command(self):
        s = ConversionSettings("in.mp4", "out.gif", fps=15, quality="high")
        cmd = self.converter.build_palettegen_command(s, "pal.png")
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("-i", cmd)
        self.assertIn("in.mp4", cmd)
        self.assertIn("pal.png", cmd)
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("palettegen=max_colors=256:stats_mode=diff", vf)

    def test_paletteuse_command(self):
        s = ConversionSettings("in.mp4", "out.gif", quality="low", loop=3)
        cmd = self.converter.build_paletteuse_command(s, "pal.png")
        lavfi = cmd[cmd.index("-lavfi") + 1]
        self.assertIn("paletteuse=dither=none", lavfi)
        self.assertEqual(cmd[cmd.index("-loop") + 1], "3")
        self.assertEqual(cmd[-1], "out.gif")

    def test_remove_segment_in_command(self):
        s = ConversionSettings(
            "in.mp4", "out.gif", remove_segments=[TimeRange(10, 20)]
        )
        cmd = self.converter.build_paletteuse_command(s, "pal.png")
        lavfi = cmd[cmd.index("-lavfi") + 1]
        self.assertIn("between(t,0,10)+gte(t,20)", lavfi)


if __name__ == "__main__":
    unittest.main()
