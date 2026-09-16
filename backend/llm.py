"""Headless Claude Code invocation for the agentic pipeline phases (Phase 2 first).
Pattern per design/02-harness-orchestration.md §4: one subprocess per file, fresh
session (no --continue), --output-format json envelope carrying result text +
total_cost_usd + usage for cost governance.
Runs with --dangerously-skip-permissions per explicit operator instruction —
--disallowedTools Bash is kept alongside it as a secondary guard, but once
permissions are skipped that is a courtesy, not a hard boundary; do not treat
these subprocesses as sandboxed."""
import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


class HeadlessInvocationError(RuntimeError):
    """Raised whenever a headless `claude -p` subprocess fails to produce a
    usable result — non-zero exit, malformed envelope, timeout, or a
    business-level failure (e.g. missing declared output files). Callers use
    the cost/token/latency fields to still log spend on a failed attempt."""

    def __init__(self, message: str, *, cost_usd: float = 0.0, input_tokens: int = 0,
                 output_tokens: int = 0, latency_ms: int = 0):
        super().__init__(message)
        self.cost_usd = cost_usd
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms


@dataclass
class ConversionResult:
    files_written: list
    cost_usd: float
    input_tokens: int
    output_tokens: int
    latency_ms: int

# Same stopgap pattern as the compiler fallbacks in routers/pipeline.py: the
# backend process PATH may not include the CLI's install dir. A real deployment
# should set CLAUDE_BIN instead of relying on a dev machine's location.
_CLAUDE_FALLBACKS = ["/home/frg/.local/bin/claude"]

# The headless `claude -p` subprocess needs a HOME with an authenticated
# Claude Code session. Default to this process's own HOME (works out of the
# box on any machine where `claude` is already logged in); set
# CLAUDE_HEADLESS_HOME to point headless calls at a different profile
# (e.g. a dedicated low-rate-limit account) without touching this file.
_HEADLESS_HOME = os.environ.get("CLAUDE_HEADLESS_HOME") or os.environ.get("HOME", "")

# Real defect found and fixed 2026-09-15: prompts cited ".claude/skills/X/SKILL.md"
# by name, but headless subprocess cwd was always the OUTPUT dir (target_dir/out_dir,
# under migration-state/runs/), never the repo root, and --add-dir only granted that
# output dir. The agent had no filesystem path to the skill file, so the citation was
# decorative — never actually read. SKILLS_DIR + the --add-dir addition below make it
# real: the skill directory is now on the agent's allowed-path list, and each prompt
# opens with an explicit instruction to Read the SKILL.md before doing anything else.
SKILLS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills"


def _skill_path(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


def _read_skill_instruction(name: str) -> str:
    return (
        f"Before anything else, Read {_skill_path(name)} in full and follow it — "
        "it is the authoritative procedure for this task, not optional background."
    )

_CONVERT_MAX_TURNS = 16  # Write several Clean Architecture files; 5 burns on Bash retries
_TIMEOUT_S = 300        # hard wall per file — a hung subprocess is a FAILED file

def find_claude() -> str | None:
    env_bin = os.environ.get("CLAUDE_BIN")
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin
    found = shutil.which("claude")
    if found:
        return found
    for p in _CLAUDE_FALLBACKS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def _parse_result_json(result_text: str) -> dict:
    """The prompt demands bare JSON, but defend against markdown fences anyway:
    parse the substring between the first '{' and the last '}'."""
    start = result_text.find("{")
    end = result_text.rfind("}")
    if start == -1 or end <= start:
        raise HeadlessInvocationError(
            f"result is not JSON (first 200 chars): {result_text[:200]!r}")
    try:
        payload = json.loads(result_text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise HeadlessInvocationError(f"result JSON parse failed: {exc}") from exc
    missing = [k for k in ("user_stories", "business_rules", "suggested_component_name")
               if k not in payload]
    if missing:
        raise HeadlessInvocationError(f"result JSON missing keys: {missing}")
    return payload


def _cost_from_envelope(envelope: dict | None) -> tuple[float, int, int]:
    """Pull billed cost/tokens from a CLI result message — including is_error ones."""
    if not envelope:
        return 0.0, 0, 0
    usage = envelope.get("usage") or {}
    inp = (
        int(usage.get("input_tokens", 0))
        + int(usage.get("cache_creation_input_tokens", 0))
        + int(usage.get("cache_read_input_tokens", 0))
    )
    out = int(usage.get("output_tokens", 0))
    return float(envelope.get("total_cost_usd", 0.0) or 0.0), inp, out


def _list_csharp_tree(target_dir: Path) -> str:
    """Plain relative paths so the doc agent sees what conversion actually wrote."""
    lines: list[str] = []
    for p in sorted(target_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(target_dir)
        if any(part in {"obj", "bin", ".git"} for part in rel.parts):
            continue
        lines.append(str(rel))
    return "\n".join(lines[:300]) if lines else "(empty)"


_PLAN_TIMEOUT_S = 90
_REPAIR_MAX_TURNS = 12


async def plan_manifest(prompt: str, source_dir: Path,
                        timeout_s: int = _PLAN_TIMEOUT_S) -> tuple[dict, dict]:
    """One JSON-only planner session. Compact inventory is already in the prompt.
    Callers: planner.plan_repository. Raises HeadlessInvocationError."""
    claude_bin = find_claude()
    if claude_bin is None:
        raise HeadlessInvocationError("claude CLI not found")
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p", prompt,
        "--output-format", "json",
        "--max-turns", "8",
        "--dangerously-skip-permissions",
        "--allowedTools", "Read,Grep,Glob",
        "--disallowedTools", "Bash,Write",
        "--add-dir", str(source_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "HOME": _HEADLESS_HOME, "ECC_GATEGUARD": "off"},
        cwd=str(source_dir),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HeadlessInvocationError(f"planner timed out after {timeout_s}s")
    latency_ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0:
        raise HeadlessInvocationError(
            f"planner exited {proc.returncode}: {stderr.decode(errors='replace')[:400]}")
    try:
        envelope = json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError as exc:
        raise HeadlessInvocationError(f"planner envelope is not JSON: {exc}") from exc
    if envelope.get("is_error"):
        raise HeadlessInvocationError(f"planner is_error: {envelope.get('result', '')[:400]}")
    start, end = envelope.get("result", "").find("{"), envelope.get("result", "").rfind("}")
    if start == -1 or end <= start:
        raise HeadlessInvocationError("planner result is not JSON")
    try:
        payload = json.loads(envelope["result"][start:end + 1])
    except json.JSONDecodeError as exc:
        raise HeadlessInvocationError(f"planner result JSON parse failed: {exc}") from exc
    if not isinstance(payload, dict) or "work_items" not in payload:
        raise HeadlessInvocationError("planner JSON missing work_items")
    usage = envelope.get("usage") or {}
    cost_meta = {
        "cost_usd": float(envelope.get("total_cost_usd", 0.0) or 0.0),
        "input_tokens": (
            int(usage.get("input_tokens", 0))
            + int(usage.get("cache_creation_input_tokens", 0))
            + int(usage.get("cache_read_input_tokens", 0))
        ),
        "output_tokens": int(usage.get("output_tokens", 0)),
        "latency_ms": latency_ms,
    }
    return payload, cost_meta


_WORK_ITEM_PROMPT = """You convert one migration work item into C#. Write ONLY the
declared files below — no undeclared Markdown, no frontend.

Work item: {title} ({kind})
Solution: {sln}
Write these paths and no others:
{expected}

COBOL / copybook sources (blocks marked "(already generated)" are real EXISTING
C# from earlier work items in THIS solution — use their real namespaces and
class names verbatim, never invent or guess a plausible-looking one):
{sources}

Rules:
- Clean Architecture backend. WORKING-STORAGE that persists across CALL → singleton.
- PIC V99 → decimal, never float/double.
- Write tool only. No Bash. Paths relative to the workspace out/ directory.
- English identifiers and comments.
- If a `README.md` is in the declared paths above, it belongs to this one leaf
  folder only: 5-10 lines, one short paragraph on what this use case/adapter
  does and which COBOL program(s) it came from — not a design doc, not a
  restatement of the code. Skip it entirely if it is not in the declared paths.
- Arithmetic (`COMPUTE`/`ADD`/`SUBTRACT`/etc.) implies truncation UNLESS the
  COBOL source has an explicit `ROUNDED` clause on that statement, in which
  case use `Math.Round(value, scale, MidpointRounding.AwayFromZero)` in C# —
  COBOL's classic `ROUNDED` default is round-half-away-from-zero, not banker's
  rounding. State which behavior applies as a one-line code comment citing the
  COBOL source line. Do not guess — check the actual source text above for the
  literal word `ROUNDED` before deciding.
- `PIC S9(a)V9(b)` (signed, implied decimal, no `SIGN IS SEPARATE`) has TWO
  DIFFERENT correct representations depending on context — verified against a
  real GnuCOBOL oracle, do not confuse them:
  * `DISPLAY`ed to console: an explicit leading `+` or `-` PLUS the decimal
    point, e.g. `+0000010.00` for positive 10.00 — use a custom format string
    like `value.ToString("+0.00;-0.00;+0.00")`, never bare `ToString()`.
  * Stored in a fixed-width FILE record: exactly `a+b` digit characters, NO
    sign character and NO decimal point (the sign is overpunched onto the
    last digit; no fixture in this repo exercises a real negative value, so
    do not add a leading sign byte there — it corrupts every downstream
    field's byte offset in that record).
  Never treat the raw on-disk digit string as an already-scaled amount or
  vice versa: always `parsed_digits / 10^b` when reading, `value * 10^b` when
  writing — a units/cents scale mixup is a silent, high-severity bug.
{cli_manifest_rule}
JSON only when done: {{"files_written": ["<relative path>", ...]}}
"""

_CLI_MANIFEST_RULE = """- `parity-manifest.json` (if declared above) is a machine-readable invocation
  contract for the Phase 6 parity gate, not documentation — write it as
  `{"programs": [{"program_id": "<PROGRAM-ID from the COBOL source, exact>",
  "argv": ["<CLI args that make Program.cs execute that program's behavior>"]}]}`,
  one entry per original COBOL program this CLI exposes. If Program.cs reads
  everything from stdin with no args needed, use `"argv": []`.
"""

# Which skill governs each work-item kind — used to grant the agent real
# filesystem access to that skill's SKILL.md (see SKILLS_DIR above).
_KIND_SKILL = {
    "conversion": "cobol-to-csharp-conversion",
    "persistence": "cobol-to-csharp-conversion",
    "cli": "cobol-to-csharp-conversion",
    "tests": "csharp-test-generation",
    "documentation": "migration-doc-generation",
}


async def convert_work_item(
    sources: dict[str, str], expected_paths: list[str], out_dir: Path,
    solution_name: str, title: str, kind: str, timeout_s: int = _TIMEOUT_S,
    on_progress=None,
    agent_circumstance: str = "",
) -> ConversionResult:
    """Isolated worker: writes only into out_dir. Callers: orchestrator."""
    claude_bin = find_claude()
    if claude_bin is None:
        raise HeadlessInvocationError("claude CLI not found")
    src_blob = "\n\n".join(
        f"--- {path} ---\n{body[:8000]}" for path, body in sources.items()
    )
    skill_name = _KIND_SKILL.get(kind, "cobol-to-csharp-conversion")
    cli_manifest_rule = _CLI_MANIFEST_RULE if kind == "cli" else ""
    prompt = _read_skill_instruction(skill_name) + "\n\n" + _WORK_ITEM_PROMPT.format(
        title=title, kind=kind, sln=solution_name,
        expected="\n".join(f"- {p}" for p in expected_paths),
        sources=src_blob, cli_manifest_rule=cli_manifest_rule,
    )
    if agent_circumstance.strip():
        prompt += (
            "\n\nAgent stack circumstance (human/agent brief — honor when compatible):\n"
            f"{agent_circumstance.strip()}\n"
        )
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", str(_CONVERT_MAX_TURNS),
        "--dangerously-skip-permissions",
        "--allowedTools", "Read,Write",
        "--disallowedTools", "Bash",
        "--add-dir", str(out_dir),
        "--add-dir", str(_skill_path(skill_name).parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "HOME": _HEADLESS_HOME, "ECC_GATEGUARD": "off"},
        cwd=str(out_dir),
    )
    envelope: dict | None = None
    stderr_chunks: list[bytes] = []

    async def _drain_stderr():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line)

    async def _read_stream():
        nonlocal envelope
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "assistant":
                for block in msg.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use" and on_progress:
                        tool_input = block.get("input") or {}
                        target = tool_input.get("file_path") or tool_input.get("path") or ""
                        on_progress(f"{block.get('name')}: {Path(target).name if target else '...'}")
            elif msg.get("type") == "result":
                envelope = msg

    try:
        await asyncio.wait_for(asyncio.gather(_read_stream(), _drain_stderr()), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HeadlessInvocationError(f"worker timed out after {timeout_s}s on {title}")
    await proc.wait()
    latency_ms = int((time.monotonic() - t0) * 1000)
    cost, inp, out = _cost_from_envelope(envelope)
    if envelope is None or envelope.get("is_error") or proc.returncode != 0:
        err = (b"".join(stderr_chunks)).decode(errors="replace")[:240]
        raise HeadlessInvocationError(
            f"worker failed {title} exit={proc.returncode} {err}",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    on_disk = [
        str(p.relative_to(out_dir)).replace("\\", "/")
        for p in out_dir.rglob("*")
        if p.is_file() and not any(part in {"obj", "bin"} for part in p.relative_to(out_dir).parts)
    ]
    if not on_disk:
        raise HeadlessInvocationError(
            f"worker wrote nothing for {title}",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    return ConversionResult(
        files_written=on_disk, cost_usd=cost, input_tokens=inp,
        output_tokens=out, latency_ms=latency_ms,
    )


_REPAIR_PROMPT = """dotnet build failed on this C# solution. Fix ONLY compile errors.
Do not add README files. Do not invent new projects.

A recurring real cause of CS0234 ("type or namespace name X does not exist in
the namespace Y") in this codebase: a `using Alias = Some.Real.Namespace;`
directive whose alias name (e.g. `Infrastructure`) collides with an actual
namespace SEGMENT already reachable from the file's own namespace (e.g. the
file is in `CobolBankingSystems.Cli` and a sibling namespace
`CobolBankingSystems.Infrastructure` exists) — the compiler can resolve the
bare identifier to the real namespace instead of the intended alias, so a
type one level deeper (e.g. `Infrastructure.Persistence.Foo`) is "not found".
If you see this pattern, rename the alias to something that cannot collide
(e.g. `Persistence` instead of `Infrastructure`) and update every reference
in that file — do not just re-add a `using` for the real namespace, that
does not fix the ambiguity.

Build output:
{errors}

Write tool only. JSON when done: {{"files_written": ["<path>", ...], "fixed": true}}
"""

# 2026-09-15 (user: "en prod debe corregirse por si mismo", "el backend se
# autocorrija sin intervencion"): Building already auto-repaired on failure —
# Testing and Parity Validation did not, so any test-compile or business-logic
# mismatch stopped the whole run cold and needed a human to hand-patch the
# generated C#. This prompt targets test-project failures specifically (a
# real, observed case: a generated test referenced namespaces/types that don't
# exist anywhere in the solution — a hallucinated API, not the real one).
_TEST_REPAIR_PROMPT = """`dotnet test` failed on this C# solution. This can be a
compile error in the test project (e.g. it references a namespace, class, or
method signature that does not actually exist anywhere in this solution — in
that case, fix the TEST file to use the real, existing API; never invent a
matching production type instead) or a genuine failing assertion (in that case,
the production code has a real bug — fix the production code, not the test).
Do not add README files. Do not invent new projects.

Test output:
{errors}

Write tool only. JSON when done: {{"files_written": ["<path>", ...], "fixed": true}}
"""

# Phase 6 (parity-validation) found a real byte-level or business-logic
# divergence between the compiled COBOL oracle and the C# candidate. Unlike a
# compile/test error, there is no exception or stack trace — just two
# recorded transcripts to compare, so the agent must diagnose the diff itself.
_PARITY_REPAIR_PROMPT = """The real COBOL program and its C# port produced
DIFFERENT output for the same input during Phase 6 parity validation. The
COBOL side is the compiled oracle — always correct by definition; fix the C#
side to match it byte-for-byte, never the other way around. Read the original
.cbl source under this directory if you need to understand a field's exact
PIC layout, sign handling (overpunch, never a separate byte, unless SIGN IS
SEPARATE is declared), or business rule.

A recurring real cause of this exact mismatch class: `PIC S9(a)V9(b)` has TWO
different correct representations. DISPLAY to console needs an explicit
leading `+`/`-` AND the decimal point (e.g. `+0000010.00`) — never bare
`ToString()`. Stored in a fixed-width FILE record it is exactly `a+b` digit
characters, NO sign byte and NO decimal point — an extra byte there shifts
every following field's offset. Also check for a units/cents scale mixup
(dividing/multiplying by 10^b at the wrong point) if the magnitude itself is
wrong, not just its formatting. Do not add README files. Do not invent new
projects.

Mismatch detail (COBOL oracle output vs C# candidate output, per program):
{errors}

Write tool only. JSON when done: {{"files_written": ["<path>", ...], "fixed": true}}
"""


async def repair_test_failure(target_dir: Path, errors: str, timeout_s: int = _TIMEOUT_S,
                              on_progress=None) -> ConversionResult:
    return await repair_csharp(target_dir, errors, timeout_s, on_progress, prompt_template=_TEST_REPAIR_PROMPT)


async def repair_parity_mismatch(target_dir: Path, errors: str, timeout_s: int = _TIMEOUT_S,
                                 on_progress=None) -> ConversionResult:
    return await repair_csharp(target_dir, errors, timeout_s, on_progress, prompt_template=_PARITY_REPAIR_PROMPT)


async def repair_csharp(target_dir: Path, errors: str, timeout_s: int = _TIMEOUT_S,
                        on_progress=None, prompt_template: str = _REPAIR_PROMPT) -> ConversionResult:
    claude_bin = find_claude()
    if claude_bin is None:
        raise HeadlessInvocationError("claude CLI not found")
    prompt = prompt_template.format(errors=errors[:12000])
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", str(_REPAIR_MAX_TURNS),
        "--dangerously-skip-permissions",
        "--allowedTools", "Read,Write",
        "--disallowedTools", "Bash",
        "--add-dir", str(target_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "HOME": _HEADLESS_HOME, "ECC_GATEGUARD": "off"},
        cwd=str(target_dir),
    )
    envelope: dict | None = None
    stderr_chunks: list[bytes] = []

    async def _drain():
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line)

    async def _read():
        nonlocal envelope
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "assistant" and on_progress:
                for block in msg.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        on_progress(str(block.get("name")))
            elif msg.get("type") == "result":
                envelope = msg

    try:
        await asyncio.wait_for(asyncio.gather(_read(), _drain()), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HeadlessInvocationError(f"repair timed out after {timeout_s}s")
    await proc.wait()
    latency_ms = int((time.monotonic() - t0) * 1000)
    cost, inp, out = _cost_from_envelope(envelope)
    if envelope is None or envelope.get("is_error") or proc.returncode != 0:
        # Real defect found 2026-09-15: this used to raise a hardcoded "repair
        # agent failed" with no reason, so a 429 session-limit, a malformed
        # stream, and a genuine unfixable compile error all looked identical.
        # Also discarded stderr entirely (_drain used to just consume and drop
        # it) — "exit=1, no result envelope" was still uninformative without it.
        # to the user. envelope["result"] carries the CLI's own explanation
        # (e.g. "You've hit your session limit") when present.
        stderr_text = b"".join(stderr_chunks).decode(errors="replace").strip()
        reason = (
            (envelope or {}).get("result")
            or stderr_text
            or f"exit={proc.returncode}, no result envelope, no stderr"
        )
        raise HeadlessInvocationError(
            f"repair agent failed: {reason}"[:400],
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    on_disk = [str(p.relative_to(target_dir)) for p in target_dir.rglob("*.cs")
               if not any(part in {"obj", "bin"} for part in p.relative_to(target_dir).parts)]
    return ConversionResult(files_written=on_disk, cost_usd=cost, input_tokens=inp,
                            output_tokens=out, latency_ms=latency_ms)


_MVP_DOCS_PROMPT = """Write exactly two files, nothing else:

README.md (solution root) — how to `dotnet build`, `dotnet test`, and run the CLI.
docs/MIGRATION.md — COBOL→C# decisions, traceability (each handler ← COBOL
PROGRAM-ID), limitations. English, dense, factual.

Existing tree:
{tree}

Write tool only. JSON: {{"files_written": ["README.md", "docs/MIGRATION.md"]}}
"""


async def write_mvp_docs(target_dir: Path, timeout_s: int = _TIMEOUT_S,
                         on_progress=None) -> ConversionResult:
    claude_bin = find_claude()
    if claude_bin is None:
        raise HeadlessInvocationError("claude CLI not found")
    tree = _list_csharp_tree(target_dir).replace("{", "{{").replace("}", "}}")
    prompt = _MVP_DOCS_PROMPT.format(tree=tree)
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p", prompt,
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", "10",
        "--dangerously-skip-permissions",
        "--allowedTools", "Read,Write",
        "--disallowedTools", "Bash",
        "--add-dir", str(target_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "HOME": _HEADLESS_HOME, "ECC_GATEGUARD": "off"},
        cwd=str(target_dir),
    )
    envelope: dict | None = None

    async def _drain():
        while await proc.stderr.readline():
            pass

    async def _read():
        nonlocal envelope
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "result":
                envelope = msg
            elif msg.get("type") == "assistant" and on_progress:
                on_progress("writing docs")

    try:
        await asyncio.wait_for(asyncio.gather(_read(), _drain()), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HeadlessInvocationError("docs timed out")
    await proc.wait()
    latency_ms = int((time.monotonic() - t0) * 1000)
    cost, inp, out = _cost_from_envelope(envelope)
    # 2026-09-15: MIGRATION.md moved under docs/ (user: "de nuevo sin carpeta
    # de docs") — this check and the extra-.md cleanup below still looked for
    # a flat "MIGRATION.md" at the solution root, so a run whose LLM correctly
    # followed the updated _MVP_DOCS_PROMPT and wrote docs/MIGRATION.md was
    # falsely reported as "docs missing" (verified: the file was genuinely
    # there, just at the new path this check didn't know about).
    if not (target_dir / "README.md").is_file() or not (target_dir / "docs" / "MIGRATION.md").is_file():
        raise HeadlessInvocationError(
            "docs missing README.md or docs/MIGRATION.md",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    extra = [
        str(p.relative_to(target_dir))
        for p in target_dir.rglob("*.md")
        if p.is_file() and str(p.relative_to(target_dir)) not in {"README.md", "docs/MIGRATION.md"}
        and not any(part in {"obj", "bin"} for part in p.relative_to(target_dir).parts)
    ]
    for rel in extra:
        (target_dir / rel).unlink()
    return ConversionResult(
        files_written=["README.md", "docs/MIGRATION.md"],
        cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
    )
