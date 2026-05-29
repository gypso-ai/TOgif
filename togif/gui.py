"""Tkinter GUI for TOgif.

A small desktop application (runs on Windows, macOS and Linux) that wraps the
:mod:`togif.converter` engine. Lets the user pick a video, configure the GIF
frame rate, quality and size, choose a time range, and remove segments (e.g.
the middle part) before converting.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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


def _optional_int(text: str, field: str) -> Optional[int]:
    text = text.strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be a whole number") from exc
    if value <= 0:
        raise ValueError(f"{field} must be a positive number")
    return value


def _optional_time(text: str, field: str) -> Optional[float]:
    text = text.strip()
    if not text:
        return None
    try:
        return parse_time(text)
    except ValueError as exc:
        raise ValueError(f"{field}: {exc}") from exc


class TogifApp(ttk.Frame):
    """Main application frame."""

    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        self.master = master
        master.title("TOgif - Video to GIF Converter")
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self._build_widgets()

    # -- UI construction --------------------------------------------------
    def _build_widgets(self) -> None:
        row = 0

        # Input file
        ttk.Label(self, text="Video file:").grid(row=row, column=0, sticky="w", pady=4)
        self.input_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.input_var).grid(
            row=row, column=1, sticky="ew", padx=4
        )
        ttk.Button(self, text="Browse...", command=self._pick_input).grid(
            row=row, column=2, padx=4
        )
        row += 1

        # Output file
        ttk.Label(self, text="Output GIF:").grid(row=row, column=0, sticky="w", pady=4)
        self.output_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.output_var).grid(
            row=row, column=1, sticky="ew", padx=4
        )
        ttk.Button(self, text="Save as...", command=self._pick_output).grid(
            row=row, column=2, padx=4
        )
        row += 1

        # Settings frame: fps / quality / size
        settings = ttk.LabelFrame(self, text="GIF settings", padding=8)
        settings.grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="Frame rate (fps):").grid(row=0, column=0, sticky="w")
        self.fps_var = tk.StringVar(value="15")
        ttk.Entry(settings, textvariable=self.fps_var, width=8).grid(
            row=0, column=1, sticky="w", padx=4
        )

        ttk.Label(settings, text="Quality:").grid(row=0, column=2, sticky="w")
        self.quality_var = tk.StringVar(value="high")
        ttk.Combobox(
            settings,
            textvariable=self.quality_var,
            values=sorted(QUALITY_PRESETS),
            state="readonly",
            width=10,
        ).grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(settings, text="Width (px):").grid(row=1, column=0, sticky="w", pady=4)
        self.width_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.width_var, width=8).grid(
            row=1, column=1, sticky="w", padx=4
        )

        ttk.Label(settings, text="Height (px):").grid(row=1, column=2, sticky="w")
        self.height_var = tk.StringVar()
        ttk.Entry(settings, textvariable=self.height_var, width=8).grid(
            row=1, column=3, sticky="w", padx=4
        )
        ttk.Label(
            settings,
            text="Leave width/height empty to keep the original size "
            "(set one to scale and keep aspect ratio).",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        row += 1

        # Trim frame
        trim = ttk.LabelFrame(self, text="Trim (keep this time range)", padding=8)
        trim.grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(trim, text="Start:").grid(row=0, column=0, sticky="w")
        self.start_var = tk.StringVar()
        ttk.Entry(trim, textvariable=self.start_var, width=12).grid(
            row=0, column=1, sticky="w", padx=4
        )
        ttk.Label(trim, text="End:").grid(row=0, column=2, sticky="w")
        self.end_var = tk.StringVar()
        ttk.Entry(trim, textvariable=self.end_var, width=12).grid(
            row=0, column=3, sticky="w", padx=4
        )
        ttk.Label(
            trim, text="Times accept seconds or HH:MM:SS. Leave empty for full video."
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        row += 1

        # Remove segments frame
        remove = ttk.LabelFrame(
            self, text="Remove segments (e.g. cut out the middle)", padding=8
        )
        remove.grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        remove.columnconfigure(0, weight=1)
        self.segments_list = tk.Listbox(remove, height=4)
        self.segments_list.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        controls = ttk.Frame(remove)
        controls.grid(row=0, column=1, sticky="n")
        ttk.Label(controls, text="Start:").grid(row=0, column=0, sticky="w")
        self.seg_start_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.seg_start_var, width=10).grid(
            row=0, column=1, padx=2
        )
        ttk.Label(controls, text="End:").grid(row=1, column=0, sticky="w")
        self.seg_end_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.seg_end_var, width=10).grid(
            row=1, column=1, padx=2
        )
        ttk.Button(controls, text="Add", command=self._add_segment).grid(
            row=0, column=2, padx=2
        )
        ttk.Button(controls, text="Remove", command=self._remove_segment).grid(
            row=1, column=2, padx=2
        )
        row += 1

        # Convert button + progress
        self.convert_btn = ttk.Button(self, text="Convert", command=self._start_convert)
        self.convert_btn.grid(row=row, column=0, columnspan=3, pady=8, sticky="ew")
        row += 1

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew")
        row += 1

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        # Internal state
        self._segments: List[TimeRange] = []

    # -- Event handlers ---------------------------------------------------
    def _pick_input(self) -> None:
        path = filedialog.askopenfilename(
            title="Select a video file",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv *.m4v"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                base, _ = os.path.splitext(path)
                self.output_var.set(base + ".gif")

    def _pick_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save GIF as",
            defaultextension=".gif",
            filetypes=[("GIF image", "*.gif")],
        )
        if path:
            self.output_var.set(path)

    def _add_segment(self) -> None:
        try:
            start = parse_time(self.seg_start_var.get())
            end = parse_time(self.seg_end_var.get())
            segment = TimeRange(start=start, end=end)
        except ValueError as exc:
            messagebox.showerror("Invalid segment", str(exc))
            return
        self._segments.append(segment)
        self.segments_list.insert(
            tk.END, f"{self.seg_start_var.get()} - {self.seg_end_var.get()}"
        )
        self.seg_start_var.set("")
        self.seg_end_var.set("")

    def _remove_segment(self) -> None:
        selection = self.segments_list.curselection()
        if not selection:
            return
        index = selection[0]
        self.segments_list.delete(index)
        del self._segments[index]

    def _collect_settings(self) -> ConversionSettings:
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        if not input_path:
            raise ValueError("Please choose a video file.")
        if not output_path:
            raise ValueError("Please choose an output GIF path.")

        fps_text = self.fps_var.get().strip()
        try:
            fps = int(fps_text)
        except ValueError as exc:
            raise ValueError("Frame rate must be a whole number.") from exc

        return ConversionSettings(
            input_path=input_path,
            output_path=output_path,
            fps=fps,
            width=_optional_int(self.width_var.get(), "Width"),
            height=_optional_int(self.height_var.get(), "Height"),
            quality=self.quality_var.get(),
            trim_start=_optional_time(self.start_var.get(), "Start"),
            trim_end=_optional_time(self.end_var.get(), "End"),
            remove_segments=list(self._segments),
        )

    def _start_convert(self) -> None:
        try:
            settings = self._collect_settings()
            settings.validate()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.convert_btn.config(state="disabled")
        self.progress.start(12)
        self.status_var.set("Starting...")

        thread = threading.Thread(
            target=self._run_conversion, args=(settings,), daemon=True
        )
        thread.start()

    def _run_conversion(self, settings: ConversionSettings) -> None:
        try:
            converter = Converter()
            converter.convert(settings, progress_callback=self._post_status)
        except (FFmpegNotFoundError, ConversionError, FileNotFoundError, ValueError) as exc:
            self.after(0, self._on_finished, False, str(exc))
            return
        self.after(0, self._on_finished, True, settings.output_path)

    def _post_status(self, message: str) -> None:
        self.after(0, self.status_var.set, message)

    def _on_finished(self, success: bool, info: str) -> None:
        self.progress.stop()
        self.convert_btn.config(state="normal")
        if success:
            self.status_var.set(f"Done: {info}")
            messagebox.showinfo("Conversion complete", f"Created:\n{info}")
        else:
            self.status_var.set("Failed.")
            messagebox.showerror("Conversion failed", info)


def main() -> int:
    root = tk.Tk()
    TogifApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
