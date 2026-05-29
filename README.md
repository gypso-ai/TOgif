# TOgif

A configurable **video → GIF** converter that runs on Windows (and macOS /
Linux). It provides both a simple desktop GUI and a command-line interface,
built on top of `ffmpeg`.

## Features

- Convert common video formats (MP4, MOV, MKV, AVI, WebM, …) to animated GIF.
- Configure the **frame rate** (fps).
- Configure the **quality** (`high` / `medium` / `low` palette presets).
- Configure the **output size** (width and/or height; aspect ratio preserved
  when only one is given).
- **Trim** the video to a time range (keep only `start`..`end`).
- **Remove segments** from the middle — e.g. cut out an unwanted middle part
  and stitch the remaining pieces together.
- High-quality output using the two-pass `palettegen` + `paletteuse` technique.

## Requirements

- Python 3.8+
- `ffmpeg`. Either:
  - install it and put it on your `PATH`, **or**
  - `pip install imageio-ffmpeg` to use a bundled binary (recommended on
    Windows — see `requirements.txt`).

```bash
pip install -r requirements.txt
```

## Running the GUI

```bash
python main.py
```

Pick a video, set the frame rate / quality / size, optionally set a trim range
and add segments to remove, then click **Convert**. On Windows, `tkinter`
ships with the standard Python installer, so no extra setup is needed.

## Command-line usage

```bash
python -m togif.cli INPUT OUTPUT [options]
```

Options:

| Option | Description |
| --- | --- |
| `--fps N` | Frames per second (default `15`). |
| `--width N` | Output width in pixels. |
| `--height N` | Output height in pixels. |
| `--quality {high,medium,low}` | Quality preset (default `high`). |
| `--start TIME` | Trim start (`SS`, `MM:SS` or `HH:MM:SS`). |
| `--end TIME` | Trim end. |
| `--remove START-END` | Remove a time segment; can be repeated. |
| `--loop N` | Loop count: `0` = forever (default), `-1` = no loop, `n` = repeat. |
| `--ffmpeg PATH` | Explicit path to `ffmpeg`. |

### Examples

Convert the whole video at 12 fps, 320 px wide:

```bash
python -m togif.cli input.mp4 output.gif --fps 12 --width 320
```

Keep only seconds 5–20:

```bash
python -m togif.cli input.mp4 output.gif --start 5 --end 20
```

Cut out the middle (remove seconds 10–20) and keep the rest:

```bash
python -m togif.cli input.mp4 output.gif --remove 10-20
```

Remove multiple segments:

```bash
python -m togif.cli input.mp4 output.gif --remove 10-20 --remove 40-50
```

## Project layout

```
main.py              # launches the GUI
togif/
  converter.py       # core ffmpeg engine (no GUI dependency)
  cli.py             # command-line interface
  gui.py             # tkinter GUI
tests/
  test_converter.py  # unit tests for the conversion logic
```

## Running the tests

```bash
python -m unittest discover -s tests
```

The tests cover the time-range and command-building logic and do not require
`ffmpeg` to be installed.
