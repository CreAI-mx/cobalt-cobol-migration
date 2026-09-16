"""Phase 6 parity gate: real, automatic, deterministic (no LLM in the pass/fail
decision). Compiles the original COBOL as an oracle, runs the generated C#
candidate against the SAME derived fixture, byte-diffs the output, and writes
one real row per program to parity_verdicts. Wired into
orchestrator.execute_migration() between the Testing gate and Documenting.

Real defect this closes (2026-09-15): the pipeline previously certified
"PASSED" from `dotnet build` + `dotnet test` alone — it never once compared
COBOL-vs-C# behavior on the same input. `_phase6_verdict()` in
routers/pipeline.py was dead code (never called); parity_demo.py is a manual
Step-5 UI button hardcoded to one program shape. This module is the real gate.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from ulid import ULID

import cobol_compilers
from cobol_io_profile import Fixture, ProgramIoProfile, derive_fixture, parse_io_profile
from models import FileEvent
from work_items import MigrationPlan, classify_kind, ready_concurrency


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: str) -> str:
    """Strip only non-functional noise — trailing whitespace per line, line
    ending style. Never touch a digit or a decision keyword."""
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


async def _compile_oracle(cbl_path: Path, work_dir: Path) -> tuple[Path | None, str]:
    cobc = cobol_compilers.find_cobc()
    if not cobc:
        return None, "cobc not found on PATH"
    env = cobol_compilers.cobc_subprocess_env(cobc)
    proc = await asyncio.create_subprocess_exec(
        cobc, "-x", "-free", cbl_path.name, "-o", "oracle",
        cwd=str(work_dir), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    oracle_bin = work_dir / "oracle"
    if not oracle_bin.is_file():
        return None, out.decode(errors="replace")[:600]
    return oracle_bin, ""


async def _run_binary(
    cmd: list[str], cwd: Path, stdin_text: str | None, timeout: int = 30,
) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        input_bytes = stdin_text.encode() if stdin_text is not None else None
        out, _ = await asyncio.wait_for(proc.communicate(input_bytes), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return False, "timed out"
    return proc.returncode == 0, out.decode(errors="replace")


def _seed_files(work_dir: Path, fixture: Fixture) -> None:
    for name, content in fixture.files.items():
        (work_dir / name).write_text(content, encoding="ascii")


def _mutated_file_names(profile: ProgramIoProfile) -> list[str]:
    return [f.assign_path for f in profile.files if f.mutated]


async def _run_cobol_side(
    cbl_path: Path, profile: ProgramIoProfile, fixture: Fixture,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="cobalt-parity-cobol-") as tmp:
        work = Path(tmp)
        shutil.copy2(cbl_path, work / cbl_path.name)
        _seed_files(work, fixture)
        oracle_bin, compile_err = await _compile_oracle(work / cbl_path.name, work)
        if oracle_bin is None:
            return False, f"COBOL_COMPILE_FAILED: {compile_err}"
        ok, stdout = await _run_binary(["./oracle"], work, fixture.stdin)
        for name in _mutated_file_names(profile):
            mutated_path = work / name
            if mutated_path.is_file():
                stdout += f"\n---FILE:{name}---\n{mutated_path.read_text(errors='replace')}"
        return ok, stdout


async def _run_csharp_side(
    dll_path: Path, argv: list[str], fixture: Fixture, mutated_names: list[str],
) -> tuple[bool, str]:
    dotnet = cobol_compilers.find_dotnet()
    if not dotnet:
        return False, "dotnet not found on PATH"
    with tempfile.TemporaryDirectory(prefix="cobalt-parity-csharp-") as tmp:
        work = Path(tmp)
        _seed_files(work, fixture)
        ok, stdout = await _run_binary([dotnet, str(dll_path), *argv], work, fixture.stdin, timeout=60)
        for name in mutated_names:
            mutated_path = work / name
            if mutated_path.is_file():
                stdout += f"\n---FILE:{name}---\n{mutated_path.read_text(errors='replace')}"
        return ok, stdout


def _find_cli_dll(csharp: Path) -> Path | None:
    # 2026-09-15: CLI project moved from "{sln}.Cli/" to "src/Cli/" (user:
    # "odia esa jerarquia de puntos") — Cli.csproj has no AssemblyName override,
    # so the built dll is "Cli.dll", not "{sln}.Cli.dll".
    candidates = list(csharp.glob("src/Cli/bin/*/net*/Cli.dll"))
    return candidates[0] if candidates else None


def _read_manifest(csharp: Path) -> dict:
    manifest_path = csharp / "src" / "Cli" / "parity-manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text())
    except (ValueError, OSError):
        return {}
    return {p.get("program_id", "").upper(): p for p in data.get("programs", [])}


async def _insert_verdict(
    conn: aiosqlite.Connection, run_id: str, program_id: str,
    cobol_output: str, csharp_output: str, match: bool,
) -> None:
    await conn.execute(
        "INSERT INTO parity_verdicts (verdict_id, run_id, fixture_name, "
        "cobol_output, csharp_output, match, divergence_class, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
        (str(ULID()), run_id, program_id, cobol_output, csharp_output, 1 if match else 0, _now()),
    )
    await conn.commit()


async def _check_one_program(
    conn: aiosqlite.Connection, run_id: str, source_dir: Path, rel_path: str,
    dll_path: Path | None, manifest: dict, events: list,
) -> tuple[bool, str, str, str]:
    """Returns (match, program_id, cobol_output, csharp_output) — the two
    outputs are always returned (even on match) so a caller can build a
    repair-agent prompt from real mismatch content, not just a pass/fail count."""
    cbl_path = source_dir / rel_path
    profile = parse_io_profile(cbl_path.read_text(errors="replace"))
    fixture = derive_fixture(profile)

    if profile.mode == "unsupported":
        await _insert_verdict(
            conn, run_id, profile.program_id, "UNSUPPORTED_IO_SHAPE", "", False,
        )
        events.append(FileEvent(
            run_id=run_id, phase="Parity Validation", file_path=profile.program_id,
            status="FAILED", detail="unsupported COBOL I/O shape — no fixture derivable",
        ))
        return False, profile.program_id, "UNSUPPORTED_IO_SHAPE", ""

    cobol_ok, cobol_output = await _run_cobol_side(cbl_path, profile, fixture)

    entry = manifest.get(profile.program_id.upper())
    if dll_path is None or entry is None:
        csharp_output = f"NO_INVOCATION_CONTRACT: parity-manifest.json missing entry for {profile.program_id}"
        match = False
    else:
        argv = entry.get("argv", [])
        mutated_names = _mutated_file_names(profile)
        csharp_ok, csharp_output = await _run_csharp_side(dll_path, argv, fixture, mutated_names)
        match = cobol_ok and csharp_ok and _normalize(cobol_output) == _normalize(csharp_output)

    await _insert_verdict(conn, run_id, profile.program_id, cobol_output, csharp_output, match)
    events.append(FileEvent(
        run_id=run_id, phase="Parity Validation", file_path=profile.program_id,
        status="OK" if match else "FAILED",
        detail="oracle matches candidate" if match else "mismatch — see parity_verdicts",
    ))
    return match, profile.program_id, cobol_output, csharp_output


async def run_parity_gate(
    conn: aiosqlite.Connection, run_id: str, plan: MigrationPlan,
    source_dir: Path, csharp: Path, events: list,
) -> tuple[bool, str]:
    """Returns (all_match, summary_detail). Inserts one parity_verdicts row per
    real COBOL program in this run. No LLM. Callers: orchestrator.execute_migration."""
    cbl_paths: list[str] = []
    for item in plan.work_items:
        if item.kind != "conversion":
            continue
        for rel in item.source_paths:
            if classify_kind(rel) == "cobol_source":
                cbl_paths.append(rel)

    if not cbl_paths:
        return True, "no COBOL sources to validate"

    dll_path = _find_cli_dll(csharp)
    manifest = _read_manifest(csharp)

    slots = ready_concurrency(len(cbl_paths))
    sem = asyncio.Semaphore(max(slots, 1))

    async def _guarded(rel: str) -> tuple[bool, str, str, str]:
        async with sem:
            return await _check_one_program(conn, run_id, source_dir, rel, dll_path, manifest, events)

    results = await asyncio.gather(*(_guarded(rel) for rel in cbl_paths))
    matched = sum(1 for r in results if r[0])
    total = len(results)
    if matched == total:
        return True, f"{matched}/{total} programs match"

    mismatches = "\n\n".join(
        f"--- {program_id} MISMATCH ---\nCOBOL (oracle) output:\n{cobol_output}\n"
        f"C# (candidate) output:\n{csharp_output}"
        for match, program_id, cobol_output, csharp_output in results if not match
    )
    return False, f"{matched}/{total} programs match\n\n{mismatches}"
