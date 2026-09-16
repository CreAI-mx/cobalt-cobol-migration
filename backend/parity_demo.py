"""Side-by-side COBOL oracle vs C# candidate — for the Step 5 parity console."""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from cobol_compilers import (
    build_fixed_width_record,
    dotnet_subprocess_env,
    find_dotnet,
    find_tool,
    run_subprocess,
)
from cobol_compilers import cobc_subprocess_env as _cobc_subprocess_env

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"
PARITY_ENGINE = "cli-oracle-v6"
_COBC_FALLBACKS = ["/home/frg/anaconda3/envs/cobol-tools/bin/cobc"]


def _find_tool(name: str, fallbacks: list[str]) -> str | None:
    return find_tool(name, fallbacks)


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    timeout: int = 90,
    env: dict[str, str] | None = None,
) -> dict:
    return run_subprocess(cmd, cwd=cwd, input_text=input_text, timeout=timeout, env=env)


def _sandbox_accounts_line(acct: str) -> str:
    num = acct.zfill(10)[:10]
    name = "COBALT SANDBOX FIXTURE".ljust(30)[:30]
    balance = "0000010000"
    return build_fixed_width_record([num, name, balance])


def _write_sandbox_accounts_dat(path: Path, acct: str) -> None:
    path.write_text(_sandbox_accounts_line(acct) + "\n", encoding="ascii")


def _find_accounts_fixture(source: Path) -> tuple[Path | None, str]:
    for dat in source.rglob("*.dat"):
        if dat.is_file():
            try:
                first = dat.read_text(errors="replace").splitlines()[0]
                digits = "".join(ch for ch in first if ch.isdigit())[:10]
                if digits:
                    return dat, digits.ljust(10, "0")[:10]
            except OSError:
                continue
    return None, "1000000001"


def _resolve_lookup_fixture(source: Path | None) -> tuple[str, str, str]:
    """Account number, accounts.dat body, note for transcript."""
    if source and source.is_dir():
        dat_src, acct = _find_accounts_fixture(source)
        if dat_src:
            body = dat_src.read_text(encoding="ascii", errors="replace")
            if not body.endswith("\n"):
                body += "\n"
            return acct, body, f"# Data: {dat_src.name}"
    acct = "1000000001"
    return acct, _sandbox_accounts_line(acct) + "\n", "# Data: synthetic accounts.dat (no .dat in run source)"


def _detect_fixture(source: Path | None) -> str:
    if source and source.is_dir():
        if next(source.rglob("account_lookup.cbl"), None):
            return "account_lookup"
    return "cobol_program"


def _cli_supports_account_lookup(program_text: str) -> bool:
    return (
        "AccountLookup" in program_text
        or "account-lookup" in program_text
        or "account_lookup.cbl" in program_text
        or ("ENTER ACCOUNT NUMBER" in program_text and "ACCOUNT FOUND" in program_text)
    )


def _find_cli_csproj(csharp: Path) -> Path | None:
    for p in sorted(csharp.rglob("*Cli*.csproj")):
        if "obj" in p.parts or "bin" in p.parts:
            continue
        program = p.parent / "Program.cs"
        if program.is_file() and _cli_supports_account_lookup(program.read_text(errors="replace")):
            return p
    return None


def _dotnet_run_cli_invocation(dotnet: str, cli: Path) -> tuple[list[str], str]:
    """Build dotnet run argv; app args after -- (never pass --nologo to the CLI exe)."""
    program = cli.parent / "Program.cs"
    text = program.read_text(errors="replace") if program.is_file() else ""
    cmd = [dotnet, "run", "--project", str(cli), "--no-launch-profile", "-v", "q"]
    if "account-lookup" in text and "args" in text:
        cmd.extend(["--", "account-lookup"])
        shown = f"dotnet run --project {cli.name} -- account-lookup"
    else:
        shown = f"dotnet run --project {cli.name}"
    return cmd, shown


def _run_cobol_oracle(source: Path, acct: str, accounts_body: str, dat_note: str) -> dict:
    cobc = _find_tool("cobc", _COBC_FALLBACKS)
    title = "COBOL — GnuCOBOL oracle"
    if not cobc:
        return {
            "title": title,
            "command": "cobc",
            "stdout": "cobc not on PATH — install GnuCOBOL to run the legacy program live.",
            "exit_code": 127,
            "ok": False,
        }

    cbl = next(source.rglob("account_lookup.cbl"), None) or next(source.rglob("*.cbl"), None)
    if cbl is None:
        return {
            "title": title,
            "command": "cobc",
            "stdout": "No .cbl source found under this run's extracted tree.",
            "exit_code": 1,
            "ok": False,
        }

    lines: list[str] = [f"# Program: {cbl.relative_to(source)}", f"# Fixture account: {acct}", dat_note]

    with tempfile.TemporaryDirectory(prefix="cobalt-cobol-") as tmp:
        work = Path(tmp)
        shutil.copy2(cbl, work / cbl.name)
        (work / "accounts.dat").write_text(accounts_body, encoding="ascii")

        cob_env = _cobc_subprocess_env(cobc)
        compile_res = _run(
            [cobc, "-x", "-free", cbl.name, "-o", "oracle"],
            cwd=work,
            env=cob_env,
        )
        lines.append(f"$ {compile_res['command']}")
        lines.append(f"# COB_CC={cob_env['COB_CC']}")
        lines.append(compile_res["stdout"].rstrip())
        oracle_bin = work / "oracle"
        if not oracle_bin.is_file():
            return {
                "title": title,
                "command": compile_res["command"],
                "stdout": "\n".join(lines),
                "exit_code": 1,
                "ok": False,
            }

        run_res = _run(["./oracle"], cwd=work, input_text=f"{acct}\n", env=cob_env)
        lines.append(f"$ echo '{acct}' | ./oracle")
        lines.append(run_res["stdout"].rstrip())
        return {
            "title": title,
            "command": run_res["command"],
            "stdout": "\n".join(lines),
            "exit_code": run_res["exit_code"],
            "ok": run_res["ok"],
        }


def _run_csharp_cli_oracle(
    csharp: Path, dotnet: str, cli: Path, acct: str, accounts_body: str,
) -> dict:
    title = "C# — CLI oracle (account lookup)"
    lines = [
        f"# Project: {cli.relative_to(csharp)}",
        f"# Fixture account: {acct}",
        "# Same accounts.dat + stdin as COBOL sandbox",
    ]
    with tempfile.TemporaryDirectory(prefix="cobalt-csharp-") as tmp:
        work = Path(tmp)
        (work / "accounts.dat").write_text(accounts_body, encoding="ascii")
        cmd, shown = _dotnet_run_cli_invocation(dotnet, cli)
        run_res = _run(
            cmd,
            cwd=work,
            input_text=f"{acct}\n",
            timeout=180,
            env=dotnet_subprocess_env(dotnet),
        )
        lines.append(f"$ echo '{acct}' | {shown}")
        lines.append(run_res["stdout"].rstrip())
        return {
            "title": title,
            "command": run_res["command"],
            "stdout": "\n".join(lines),
            "exit_code": run_res["exit_code"],
            "ok": run_res["ok"],
        }


def _test_sources_in_project(test_csproj: Path) -> list[Path]:
    root = test_csproj.parent
    skip = {"bin", "obj"}
    return [
        p
        for p in root.rglob("*.cs")
        if p.is_file() and not any(part in skip for part in p.parts)
    ]


def _dotnet_build_gate(dotnet: str, csproj: Path, timeout: int = 180) -> dict:
    cmd = [dotnet, "build", str(csproj), "--verbosity", "minimal", "--nologo"]
    res = _run(cmd, cwd=csproj.parent, timeout=timeout, env=dotnet_subprocess_env(dotnet))
    out = res["stdout"]
    ok = res["ok"] and "Build succeeded" in out and "0 Error(s)" in out
    note = (
        "\n\n# No CLI oracle / xUnit tests — parity falls back to dotnet build only."
    )
    return {**res, "stdout": out.rstrip() + note, "ok": ok, "command": res["command"]}


def _run_csharp_fallback(csharp: Path, dotnet: str) -> dict:
    title = "C# — dotnet test"
    test_csproj = next(csharp.rglob("*Tests.csproj"), None)
    if test_csproj is None:
        build_target = next(csharp.rglob("*.sln"), None) or next(csharp.rglob("*.csproj"), None)
        if build_target is None:
            return {
                "title": title,
                "command": "dotnet build",
                "stdout": "No .csproj under generated C#.",
                "exit_code": 1,
                "ok": False,
            }
        return {**_dotnet_build_gate(dotnet, build_target), "title": title}

    sources = _test_sources_in_project(test_csproj)
    has_xunit = any(
        "[Fact]" in src.read_text(errors="replace") or "[Theory]" in src.read_text(errors="replace")
        for src in sources
    )
    if not has_xunit:
        return {**_dotnet_build_gate(dotnet, test_csproj), "title": title}

    cmd = [dotnet, "test", str(test_csproj), "--verbosity", "normal", "--nologo"]
    res = _run(cmd, cwd=csharp, timeout=180, env=dotnet_subprocess_env(dotnet))
    out = res["stdout"]
    if res["ok"] and ("No test is available" in out or "Total tests: 0" in out):
        return {**_dotnet_build_gate(dotnet, test_csproj), "title": title}
    return {**res, "title": title}


def _run_csharp_side(
    csharp: Path,
    fixture: str,
    acct: str,
    accounts_body: str,
) -> dict:
    dotnet = find_dotnet()
    if not dotnet:
        return {
            "title": "C# — CLI oracle",
            "command": "dotnet run",
            "stdout": "dotnet SDK not on PATH.",
            "exit_code": 127,
            "ok": False,
        }
    if not csharp.is_dir():
        return {
            "title": "C# — CLI oracle",
            "command": "dotnet run",
            "stdout": "No generated C# folder for this run yet.",
            "exit_code": 1,
            "ok": False,
        }

    if fixture == "account_lookup":
        cli = _find_cli_csproj(csharp)
        if cli:
            return _run_csharp_cli_oracle(csharp, dotnet, cli, acct, accounts_body)

    return _run_csharp_fallback(csharp, dotnet)




def _normalize_stdout(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


def _meaningful_stdout_lines(text: str) -> list[str]:
    norm = _normalize_stdout(text)
    lines = [
        ln.strip()
        for ln in norm.splitlines()
        if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith("$ ")
    ]
    if lines:
        return lines
    return [norm.strip()] if norm.strip() else []


_MAX_LINE_DIFFS = 40


def _build_line_comparison(cobol: dict, csharp: dict) -> dict:
    cob_norm = _normalize_stdout(cobol.get("stdout") or "")
    cs_norm = _normalize_stdout(csharp.get("stdout") or "")
    cl = _meaningful_stdout_lines(cobol.get("stdout") or "")
    csl = _meaningful_stdout_lines(csharp.get("stdout") or "")
    row_count = min(max(len(cl), len(csl), 1), _MAX_LINE_DIFFS)
    diffs: list[dict] = []
    for i in range(row_count):
        cb = cl[i] if i < len(cl) else "—"
        cs = csl[i] if i < len(csl) else "—"
        eq = cb == cs
        diffs.append({
            "field": f"line-{i + 1}",
            "label": f"Line {i + 1}",
            "equal": eq,
            "cobol": cb,
            "csharp": cs,
            "fix_hint": None if eq else (
                "Align migrated stdout with legacy COBOL for this line (DISPLAY/WRITE)."
            ),
        })
    if max(len(cl), len(csl)) > _MAX_LINE_DIFFS:
        diffs.append({
            "field": "truncated",
            "label": "…",
            "equal": len(cl) == len(csl),
            "cobol": f"{len(cl)} line(s)",
            "csharp": f"{len(csl)} line(s)",
            "fix_hint": f"Showing first {_MAX_LINE_DIFFS} lines — compare full transcripts in the terminals.",
        })
    output_equal = cob_norm == cs_norm
    return {
        "output_equal": output_equal,
        "display_equal": output_equal,
        "mode": "lines",
        "diffs": diffs,
    }

def _lookup_outcome(stdout: str) -> str | None:
    u = stdout.upper()
    if "ACCOUNT NOT FOUND" in u:
        return "not_found"
    if "ACCOUNT FOUND" in u:
        return "found"
    return None


def _extract_name(stdout: str) -> str | None:
    for line in stdout.splitlines():
        m = re.match(r"NAME:\s*(.+)", line.strip(), re.I)
        if m:
            return m.group(1).strip()
    return None




def _parse_balance_value(raw: str | None) -> float | None:
    if not raw:
        return None
    s = raw.strip().replace("+", "").replace(",", "")
    if not s:
        return None
    try:
        if "." in s:
            return float(s)
        # Implied decimal S9(7)V99 (10 digit field → scale 2)
        if s.isdigit() and len(s) >= 3:
            return int(s) / 100.0
        return float(s)
    except ValueError:
        return None


def _build_structured_lookup_comparison(cobol: dict, csharp: dict) -> dict | None:
    if not cobol.get("ok") or not csharp.get("ok"):
        return None
    cob_out = _lookup_outcome(cobol["stdout"])
    cs_out = _lookup_outcome(csharp["stdout"])
    if not cob_out or not cs_out:
        return None

    cn, sn = _extract_name(cobol["stdout"]), _extract_name(csharp["stdout"])
    cb_raw = None
    cs_raw = None
    for line in cobol["stdout"].splitlines():
        m = re.match(r"BALANCE:\s*(.+)", line.strip(), re.I)
        if m:
            cb_raw = m.group(1).strip()
    for line in csharp["stdout"].splitlines():
        m = re.match(r"BALANCE:\s*(.+)", line.strip(), re.I)
        if m:
            cs_raw = m.group(1).strip()

    cb_val = _parse_balance_value(cb_raw)
    cs_val = _parse_balance_value(cs_raw)

    diffs: list[dict] = []

    outcome_eq = cob_out == cs_out
    diffs.append({
        "field": "outcome",
        "label": "Outcome (FOUND / NOT FOUND)",
        "equal": outcome_eq,
        "cobol": "ACCOUNT FOUND" if cob_out == "found" else "ACCOUNT NOT FOUND",
        "csharp": "ACCOUNT FOUND" if cs_out == "found" else "ACCOUNT NOT FOUND",
        "fix_hint": None if outcome_eq else (
            "Fix account lookup in the C# Handler/CLI to match COBOL READ/PERFORM."
        ),
    })

    name_eq = (cn or "").strip().upper() == (sn or "").strip().upper()
    diffs.append({
        "field": "name",
        "label": "NAME",
        "equal": name_eq,
        "cobol": cn or "—",
        "csharp": sn or "—",
        "fix_hint": None if name_eq else (
            "Check accounts.dat parsing (width 30) or Trim in Program.cs / repository."
        ),
    })

    balance_display_eq = (cb_raw or "") == (cs_raw or "")
    balance_value_eq = cb_val == cs_val if cb_val is not None and cs_val is not None else balance_display_eq
    balance_eq = balance_value_eq
    fix_balance = None
    if not balance_eq:
        if balance_value_eq is False and cb_val is not None and cs_val is not None:
            fix_balance = (
                f"Numeric value differs (COBOL≈{cb_val} vs C#≈{cs_val}). "
                "Review PIC S9(7)V99, decimal scale, and file read."
            )
        elif not balance_display_eq:
            fix_balance = (
                "Display format differs. In *Cli/Program.cs format BALANCE like COBOL DISPLAY "
                "(sign + zero padding + decimals, e.g. +0000010.00)."
            )

    diffs.append({
        "field": "balance",
        "label": "BALANCE",
        "equal": balance_eq,
        "cobol": cb_raw or "—",
        "csharp": cs_raw or "—",
        "fix_hint": fix_balance,
        "display_equal": balance_display_eq,
        "numeric_equal": balance_value_eq,
    })

    output_equal = outcome_eq and name_eq and balance_eq
    display_equal = output_equal and balance_display_eq

    return {
        "output_equal": output_equal,
        "display_equal": display_equal,
        "mode": "structured",
        "diffs": diffs,
    }


def _build_comparison(cobol: dict, csharp: dict) -> dict | None:
    if not (cobol.get("stdout") or "").strip() and not (csharp.get("stdout") or "").strip():
        return None
    if cobol.get("ok") and csharp.get("ok"):
        structured = _build_structured_lookup_comparison(cobol, csharp)
        if structured:
            return structured
    return _build_line_comparison(cobol, csharp)


def _verdict(cobol: dict, csharp: dict) -> tuple[str, str]:
    if not cobol["ok"] and not csharp["ok"]:
        return "blocked", "Neither side ran cleanly — check compilers and the run output."
    if not cobol["ok"]:
        return "partial", "C# ran; COBOL oracle failed (cobc / compile / missing accounts.dat)."
    if not csharp["ok"]:
        return "partial", "COBOL ran; C# candidate failed."

    cob_out = _lookup_outcome(cobol["stdout"])
    cs_out = _lookup_outcome(csharp["stdout"])
    if cob_out and cs_out:
        if cob_out != cs_out:
            return "partial", f"Lookup diverges: COBOL={cob_out}, C#={cs_out}."
        if cob_out == "found":
            cn, sn = _extract_name(cobol["stdout"]), _extract_name(csharp["stdout"])
            if cn and sn and cn.upper() != sn.upper():
                return "review", "Both FOUND — compare NAME/BALANCE formatting."
            return "match", "Same lookup transcript: ACCOUNT FOUND on COBOL and C# CLI."
        return "match", "Both report ACCOUNT NOT FOUND for the fixture."

    cs = csharp["stdout"]
    if "falls back to dotnet build" in cs:
        return "partial", "COBOL ran; C# only built (no CLI oracle / tests)."
    if "PASSED" in cs.upper() and cobol["ok"]:
        return "match", "COBOL OK and C# test gate passed."
    return "review", "Both exited OK — compare transcripts manually."


def _idle_cobol() -> dict:
    return {
        "title": "COBOL — GnuCOBOL oracle",
        "command": "",
        "stdout": "$ sandbox idle — run to compile & execute legacy .cbl",
        "exit_code": 0,
        "ok": True,
    }


def _idle_csharp() -> dict:
    return {
        "title": "C# — CLI oracle",
        "command": "",
        "stdout": "$ sandbox idle — run migrated CLI with same accounts.dat + stdin",
        "exit_code": 0,
        "ok": True,
    }


def run_parity_demo(run_id: str, side: str = "both") -> dict:
    side = (side or "both").lower()
    if side not in {"both", "cobol", "csharp"}:
        side = "both"

    source = RUNS_DIR / run_id / "source"
    csharp_dir = RUNS_DIR / run_id / "csharp"
    src = source if source.is_dir() else None
    fixture = _detect_fixture(src)
    acct, accounts_body, dat_note = _resolve_lookup_fixture(src)

    cobol = _idle_cobol()
    csharp = _idle_csharp()

    if side in {"both", "cobol"}:
        if src:
            cobol = _run_cobol_oracle(src, acct, accounts_body, dat_note)
        else:
            cobol = {
                "title": "COBOL — GnuCOBOL oracle",
                "command": "",
                "stdout": "No extracted source for this run.",
                "exit_code": 1,
                "ok": False,
            }

    if side in {"both", "csharp"}:
        csharp = _run_csharp_side(csharp_dir, fixture, acct, accounts_body)

    if side == "cobol":
        verdict, summary = (
            ("match", "COBOL sandbox finished OK.") if cobol["ok"] else ("blocked", "COBOL sandbox failed.")
        )
    elif side == "csharp":
        verdict, summary = (
            ("match", "C# sandbox finished OK.") if csharp["ok"] else ("blocked", "C# sandbox failed.")
        )
    else:
        verdict, summary = _verdict(cobol, csharp)

    comparison = None
    if side in {"both", "csharp", "cobol"}:
        comparison = _build_comparison(cobol, csharp)

    return {
        "run_id": run_id,
        "side": side,
        "parity_engine": PARITY_ENGINE,
        "fixture": fixture if side != "csharp" else fixture,
        "cobol": cobol,
        "csharp": csharp,
        "verdict": verdict,
        "summary": summary,
        "comparison": comparison,
    }
