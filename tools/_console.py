"""
Console encoding, fixed once.

Windows consoles default to cp1252, which cannot encode the box-drawing characters and
section signs these reports are full of — and the failure mode is a `UnicodeEncodeError`
that kills the tool **mid-report**, after it has already printed half its output. That
happened three times while building the P1 tooling, each time on a different tool.

`errors="replace"` rather than a strict re-encode: a report that renders one character
as `?` is a cosmetic problem, and a report that dies at line 40 of 200 is not.

Import for the side effect, before anything prints:

    from tools import _console  # noqa: F401
"""

from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass       # already UTF-8, or not a real stream (pytest capture)
