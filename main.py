#!/usr/bin/env python3
"""Entry point that launches the TOgif GUI.

Run ``python main.py`` to open the graphical interface, or use
``python -m togif.cli ...`` for the command-line interface.
"""

from togif.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
