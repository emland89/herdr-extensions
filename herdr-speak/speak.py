#!/usr/bin/env python3
"""Speak: hear your coding agents in Herdr. Herdr runs this for every action.

Usage: python3 speak.py <command>   (see `python3 speak.py --help`)
"""

import os
import sys

if sys.version_info < (3, 9):  # noqa: UP036  (a clear message on older systems)
    sys.exit("Speak needs Python 3.9 or newer for its launcher")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from herdr_speak.commands import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv))
