"""Deterministic (no LLM) classification of a COBOL program's I/O shape, and
derivation of a canonical, deterministic input fixture from it — the ground
truth the Phase 6 parity gate (parity_gate.py) feeds to both the real COBOL
oracle and the generated C# candidate.

Real defect this replaces (2026-09-15): earlier assumption was "every COBOL
program reads one value via ACCEPT". Verified against the 3 real .cbl files in
today's demo repo (cobol-banking-systems), that is true for only 1 of 3:
- aml_flagging.cbl: 2 ACCEPTs, no files at all -> "interactive"
- account_lookup.cbl: 1 ACCEPT + a read-only SELECT/FD (accounts.dat), no
  REWRITE/WRITE anywhere -> "interactive_with_lookup_file"
- transaction_posting.cbl: zero ACCEPTs, two files, REWRITE on one -> "file_batch",
  whose real output is the mutated file, not stdout (its only stdout is a
  conditional "ACCOUNT NOT FOUND" error line).

Same regex style as work_items.py's PROGRAM_ID_RE/CALL_RE — no ProLeap
dependency here yet; swapping in a real parser later only means feeding this
module a structured parse instead of running its own regex.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from cobol_layout import compute_pic_width
from work_items import PROGRAM_ID_RE

_SELECT_RE = re.compile(
    r'SELECT\s+([\w-]+)\s+ASSIGN\s+TO\s+"([^"]+)"', re.IGNORECASE,
)
_FD_RE = re.compile(r"^\s*FD\s+([\w-]+)\.", re.IGNORECASE | re.MULTILINE)
_RECORD_FIELD_RE = re.compile(
    r"^\s*\d\d\s+([\w-]+)\s+PIC\s+([S9AXV()0-9]+)", re.IGNORECASE | re.MULTILINE,
)
_ACCEPT_RE = re.compile(r"\bACCEPT\s+([\w-]+)", re.IGNORECASE)
_MUTATE_RE = re.compile(r"\b(?:REWRITE|WRITE)\s+([\w-]+)", re.IGNORECASE)
_SECTION_SPLIT_RE = re.compile(
    r"^\s*(PROCEDURE\s+DIVISION|WORKING-STORAGE\s+SECTION|FILE\s+SECTION)\b",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class AcceptField:
    var_name: str
    pic: str
    sign_separate: bool = False


@dataclass(frozen=True)
class FileSpec:
    select_name: str
    assign_path: str
    record_name: str
    record_pics: list[str]
    mutated: bool


@dataclass(frozen=True)
class ProgramIoProfile:
    program_id: str
    mode: Literal["interactive", "interactive_with_lookup_file", "file_batch", "unsupported"]
    accepts: list[AcceptField] = field(default_factory=list)
    files: list[FileSpec] = field(default_factory=list)


def _split_sections(cbl_text: str) -> dict[str, str]:
    """Best-effort slice of the source into named sections by their headers,
    so field/PIC lookups don't accidentally match across divisions."""
    matches = list(_SECTION_SPLIT_RE.finditer(cbl_text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        name = m.group(1).upper().split()[0]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cbl_text)
        sections[name] = cbl_text[m.start():end]
    return sections


def _parse_files(cbl_text: str, file_section: str, procedure_text: str) -> list[FileSpec]:
    selects = _SELECT_RE.findall(cbl_text)  # [(select_name, assign_path), ...]
    mutated_records = {m.upper() for m in _MUTATE_RE.findall(procedure_text)}

    fd_blocks: dict[str, str] = {}
    fd_matches = list(_FD_RE.finditer(file_section))
    for i, m in enumerate(fd_matches):
        name = m.group(1).upper()
        end = fd_matches[i + 1].start() if i + 1 < len(fd_matches) else len(file_section)
        fd_blocks[name] = file_section[m.start():end]

    files: list[FileSpec] = []
    for select_name, assign_path in selects:
        block = fd_blocks.get(select_name.upper(), "")
        fields = _RECORD_FIELD_RE.findall(block)
        record_match = re.search(r"^\s*01\s+([\w-]+)\.", block, re.IGNORECASE | re.MULTILINE)
        record_name = record_match.group(1).upper() if record_match else select_name
        record_pics = [pic for _name, pic in fields]
        files.append(FileSpec(
            select_name=select_name.upper(),
            assign_path=assign_path,
            record_name=record_name,
            record_pics=record_pics,
            mutated=record_name in mutated_records,
        ))
    return files


def _parse_accepts(procedure_text: str, working_storage_text: str) -> list[AcceptField]:
    var_names = _ACCEPT_RE.findall(procedure_text)
    accepts: list[AcceptField] = []
    for var in var_names:
        m = re.search(
            rf"^\s*\d\d\s+{re.escape(var)}\s+PIC\s+([S9AXV()0-9]+)",
            working_storage_text, re.IGNORECASE | re.MULTILINE,
        )
        if not m:
            continue
        pic = m.group(1)
        # Same-line SIGN IS SEPARATE check — none of today's real fields use
        # it, but real customer COBOL might; do not silently assume False
        # without looking.
        line_end = working_storage_text.find("\n", m.end())
        line_end = line_end if line_end != -1 else len(working_storage_text)
        rest_of_clause = working_storage_text[m.end():line_end]
        sign_separate = "SIGN" in rest_of_clause.upper() and "SEPARATE" in rest_of_clause.upper()
        accepts.append(AcceptField(var_name=var, pic=pic, sign_separate=sign_separate))
    return accepts


def parse_io_profile(cbl_text: str) -> ProgramIoProfile:
    program_match = PROGRAM_ID_RE.search(cbl_text)
    program_id = program_match.group(1) if program_match else "UNKNOWN"

    sections = _split_sections(cbl_text)
    procedure_text = sections.get("PROCEDURE", "")
    working_storage_text = sections.get("WORKING-STORAGE", "")
    file_section = sections.get("FILE", "")

    accepts = _parse_accepts(procedure_text, working_storage_text)
    files = _parse_files(cbl_text, file_section, procedure_text)

    has_mutation = any(f.mutated for f in files)
    if accepts and not files:
        mode: str = "interactive"
    elif accepts and files and not has_mutation:
        mode = "interactive_with_lookup_file"
    elif not accepts and files and has_mutation:
        mode = "file_batch"
    else:
        mode = "unsupported"

    return ProgramIoProfile(program_id=program_id, mode=mode, accepts=accepts, files=files)


def _numeric_fixture_value(pic: str, sign_separate: bool) -> str:
    width = compute_pic_width(pic, sign_separate=sign_separate)
    return str(9999999999 % (10 ** width)).zfill(width)


def _alpha_fixture_value(width: int) -> str:
    tile = "COBALTFIXTURE"
    return (tile * (width // len(tile) + 1))[:width]


def _field_fixture_value(pic: str) -> str:
    if pic.upper().lstrip("S").startswith("X"):
        m = re.search(r"\((\d+)\)", pic)
        width = int(m.group(1)) if m else pic.upper().count("X")
        return _alpha_fixture_value(width)
    return _numeric_fixture_value(pic, sign_separate=False)


@dataclass(frozen=True)
class Fixture:
    stdin: str | None
    files: dict[str, str]  # assign_path -> file content


def derive_fixture(profile: ProgramIoProfile) -> Fixture:
    stdin_lines = [_field_fixture_value(a.pic) for a in profile.accepts]
    stdin = ("\n".join(stdin_lines) + "\n") if stdin_lines else None

    files: dict[str, str] = {}
    mutated = next((f for f in profile.files if f.mutated), None)
    key_value = None
    if mutated and mutated.record_pics:
        key_value = _field_fixture_value(mutated.record_pics[0])

    for f in profile.files:
        record_values = list(f.record_pics)
        if key_value is not None and record_values:
            # Non-mutated lookup files share the mutated file's key so the
            # program's normal (found/matched) path runs, not its error path
            # — v1 exercises the happy path only.
            values = [key_value] + [_field_fixture_value(p) for p in record_values[1:]]
        else:
            values = [_field_fixture_value(p) for p in record_values]
        files[f.assign_path] = "".join(values) + "\n"

    return Fixture(stdin=stdin, files=files)
