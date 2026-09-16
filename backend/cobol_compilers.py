"""Shared, environment-fragile compiler plumbing for GnuCOBOL/dotnet subprocess
invocation. Extracted from parity_demo.py so the manual Step-5 demo button and
the automatic Phase 6 parity gate (parity_gate.py) share one fix, not two
copies that can drift. The COB_CC override here is the real fix (verified
2026-09-15) for conda-packaged cobc embedding a build-machine CC path that
does not exist on this host.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_COBC_FALLBACKS = ["/home/frg/anaconda3/envs/cobol-tools/bin/cobc"]
_DOTNET_FALLBACKS = ["/home/frg/.claude3_profile/.dotnet/dotnet"]


def find_tool(name: str, fallbacks: list[str]) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for p in fallbacks:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def dotnet_root_for(dotnet_bin: str) -> str:
    return str(Path(dotnet_bin).resolve().parent)


def dotnet_subprocess_env(dotnet_bin: str) -> dict[str, str]:
    env = os.environ.copy()
    root = dotnet_root_for(dotnet_bin)
    env["DOTNET_ROOT"] = root
    env["PATH"] = f"{root}{os.pathsep}{env.get('PATH', '')}"
    return env


def _dotnet_usable(dotnet_bin: str) -> bool:
    env = dotnet_subprocess_env(dotnet_bin)
    try:
        proc = subprocess.run(
            [dotnet_bin, "--version"],
            capture_output=True,
            timeout=20,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    err = (proc.stderr or b"").decode(errors="replace").lower()
    return "hostfxr" not in err and "does not exist" not in err


def find_dotnet() -> str | None:
    candidates: list[str] = []
    for path in (shutil.which("dotnet"), *_DOTNET_FALLBACKS):
        if not path or path in candidates:
            continue
        if os.path.isfile(path) and os.access(path, os.X_OK):
            candidates.append(path)
    for c in candidates:
        if _dotnet_usable(c):
            return c
    return None


def find_cobc() -> str | None:
    return find_tool("cobc", _COBC_FALLBACKS)


def cobc_subprocess_env(cobc: str) -> dict[str, str]:
    """Conda-packaged cobc embeds a build-machine CC path; override with host gcc."""
    env = os.environ.copy()
    gcc = shutil.which("gcc") or "/usr/bin/gcc"
    ld = shutil.which("ld") or "/usr/bin/ld"
    env["COB_CC"] = gcc
    env["COB_LD"] = ld
    lib = Path(cobc).resolve().parent.parent / "lib"
    if lib.is_dir():
        prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lib}{':' + prev if prev else ''}"
    return env


def run_subprocess(
    cmd: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    timeout: int = 90,
    env: dict[str, str] | None = None,
) -> dict:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            input=input_text.encode() if input_text is not None else None,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env if env is not None else None,
        )
        out = (proc.stdout + proc.stderr).decode(errors="replace")
        return {
            "command": " ".join(cmd),
            "stdout": out,
            "exit_code": proc.returncode,
            "ok": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(cmd),
            "stdout": f"(timed out after {timeout}s)",
            "exit_code": -1,
            "ok": False,
        }
    except FileNotFoundError:
        return {
            "command": " ".join(cmd),
            "stdout": f"command not found: {cmd[0]}",
            "exit_code": 127,
            "ok": False,
        }


def build_fixed_width_record(field_values: list[str]) -> str:
    """Concatenate already-formatted, already-padded field values into one
    fixed-width DISPLAY record line. Generalizes parity_demo._sandbox_accounts_line
    (which hand-coded exactly this pattern for one record shape) so any
    caller building a synthetic .dat line uses one shared implementation."""
    return "".join(field_values)
