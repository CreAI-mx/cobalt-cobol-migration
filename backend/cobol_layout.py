"""Byte-width ground truth for COBOL fixed-length DISPLAY records.

Root cause this exists for (real audit, 2026-09-15): an independent architect
review of a manual COBOL-to-C# migration (run 01M2K8AVCR27QJFFKS243K1E8K,
csharp-reference/) found the generated record codec invented a self-consistent
but WRONG byte layout — e.g. it always emitted a leading sign character (10
bytes) for a field the COBOL source declares as `PIC S9(7)V99` DISPLAY, which
is 9 bytes with the sign overpunched onto the last digit, never a separate
character, since the source has no `SIGN IS SEPARATE` clause. The accompanying
unit tests round-tripped the codec against itself, so the wrong width was
self-consistent and undetectable from the C# side alone.

This module computes the width mechanically from the PIC clause text so it can
be quoted at the LLM (Phase 4 conversion prompt) as ground truth instead of
being re-derived — and re-derivable wrong — by the model each time.
"""
from __future__ import annotations

import re

_REPEAT_RE = re.compile(r"\((\d+)\)")


def _digit_count(pic_numeric_part: str) -> int:
    """Count digit positions in a PIC clause fragment like '9(7)V99' or '999'."""
    total = 0
    i = 0
    while i < len(pic_numeric_part):
        ch = pic_numeric_part[i]
        if ch == "V":
            i += 1
            continue
        if ch == "9":
            match = _REPEAT_RE.match(pic_numeric_part, i + 1)
            if match:
                total += int(match.group(1))
                i = match.end()
            else:
                total += 1
                i += 1
            continue
        i += 1
    return total


def compute_pic_width(pic: str, sign_separate: bool = False) -> int:
    """Byte width of a single DISPLAY-usage PIC clause.

    `PIC 9(n)` -> n bytes. `PIC X(n)` -> n bytes. `PIC S9(a)V9(b)` -> a+b bytes,
    with the sign overpunched onto the last digit (no extra byte) unless the
    field carries an explicit SIGN IS SEPARATE clause, which is not inferable
    from the PIC clause alone and must be passed in from the surrounding FD.
    """
    pic = pic.strip().upper()
    is_signed = pic.startswith("S")
    body = pic[1:] if is_signed else pic

    if body.startswith("X"):
        match = _REPEAT_RE.search(body)
        return int(match.group(1)) if match else body.count("X")

    width = _digit_count(body)
    if is_signed and sign_separate:
        width += 1
    return width


def compute_record_width(pics: list[str], sign_separate: bool = False) -> int:
    """Sum of `compute_pic_width` over every field in a record, in FD order."""
    return sum(compute_pic_width(p, sign_separate=sign_separate) for p in pics)
