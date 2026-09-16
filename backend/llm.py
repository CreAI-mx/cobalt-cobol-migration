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

# COBALT-5 (audit 2026-09-16): a `claude -p` child was only ever killed by
# the asyncio.TimeoutError branch inside its OWN awaiting coroutine — if the
# uvicorn PARENT dies instead (crash, kill -9, the exact two-session
# collision seen this session), every in-flight child is orphaned to init
# and keeps running/spending tokens with nothing tracking or killing it.
# Every spawn below registers here; main.py's shutdown handler kills
# whatever is still alive when the app itself is stopped.
_ACTIVE_HEADLESS_PROCS: set = set()


def _claude_code_env() -> dict[str, str]:
    """Use the authenticated Claude Code Pro session, never a stale API key.

    The exploration/docs flow is intentionally driven by the Claude Code CLI.
    An inherited ANTHROPIC_API_KEY makes that CLI choose API-key auth first and
    can turn a healthy Pro login into a 401 before the agent starts.
    """
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    env.update({"HOME": _HEADLESS_HOME, "ECC_GATEGUARD": "off"})
    return env


def kill_all_active_headless_processes() -> int:
    """Called from main.py's shutdown handler. Returns how many were killed."""
    killed = 0
    for proc in list(_ACTIVE_HEADLESS_PROCS):
        if proc.returncode is None:
            try:
                proc.kill()
                killed += 1
            except ProcessLookupError:
                pass
    return killed

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
        env=_claude_code_env(),
        cwd=str(source_dir),
    )
    _ACTIVE_HEADLESS_PROCS.add(proc)
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


async def extract_exploration_rules(source_dir: Path, member_paths: list[str],
                                    draft_rules: list[dict], timeout_s: int = 180) -> tuple[list[dict], dict]:
    """Read-only Claude Code pass for evidence-backed AS-IS rules."""
    claude_bin = find_claude()
    if claude_bin is None:
        raise HeadlessInvocationError("claude CLI not found")
    prompt = """Read the COBOL source. Extract only AS-IS business rules.
Use simple English internally. Do not write files. Do not discuss migration.
Every rule must have one or more exact anchors in `file:line` format. Return
only JSON: {{\"business_rules\":[{{\"text\":\"...\",\"anchors\":[\"file:12\"],\"source\":\"agent\"}}]}}.
If evidence is insufficient, return an empty list.

Member paths: {paths}
Deterministic candidates (verify or replace): {drafts}
""".format(paths=json.dumps(member_paths), drafts=json.dumps(draft_rules))
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p", prompt, "--output-format", "json", "--max-turns", "8",
        "--dangerously-skip-permissions", "--allowedTools", "Read,Grep,Glob",
        "--disallowedTools", "Bash,Write", "--add-dir", str(source_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=_claude_code_env(), cwd=str(source_dir),
    )
    _ACTIVE_HEADLESS_PROCS.add(proc)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HeadlessInvocationError("business-rule agent timed out")
    latency_ms = int((time.monotonic() - t0) * 1000)
    try:
        envelope = json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError as exc:
        raise HeadlessInvocationError("business-rule agent envelope is not JSON") from exc
    cost, inp, out = _cost_from_envelope(envelope)
    if proc.returncode != 0 or envelope.get("is_error"):
        raise HeadlessInvocationError(
            f"business-rule agent failed: {(envelope.get('result') or stderr.decode(errors='replace'))[:300]}",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    result = str(envelope.get("result", ""))
    start, end = result.find("{"), result.rfind("}")
    try:
        payload = json.loads(result[start:end + 1])
    except (json.JSONDecodeError, ValueError) as exc:
        raise HeadlessInvocationError("business-rule agent result is not JSON", cost_usd=cost,
                                     input_tokens=inp, output_tokens=out, latency_ms=latency_ms) from exc
    rules = payload.get("business_rules")
    if not isinstance(rules, list):
        raise HeadlessInvocationError("business-rule agent result missing business_rules", cost_usd=cost,
                                     input_tokens=inp, output_tokens=out, latency_ms=latency_ms)
    return rules, {"cost_usd": cost, "input_tokens": inp, "output_tokens": out,
                   "latency_ms": latency_ms, "ok": bool(rules), "reason": ""}


async def extract_estate_relation_graph(
    source_dir: Path, candidates: dict, timeout_s: int = 360,
) -> tuple[dict, dict]:
    """Importers: exploration_orchestrator._agentic_relation_graph.

    Returns one AS-IS relation+sequence graph (schema 2) plus cost_meta.
    User: "quiero un diagrama de relacion secuencia uno solo, un grafo,
    pero esto debe ser construido agenticamente".
    """
    claude_bin = find_claude()
    if claude_bin is None:
        raise HeadlessInvocationError("claude CLI not found")
    inventory = json.dumps(candidates, ensure_ascii=False)[:6000]
    prompt = """Read the COBOL. Produce ONE relation+sequence GRAPH of how the
estate hangs together as a business system.

FORBIDDEN:
- A flowchart of the original scripts (no DISPLAY/ACCEPT/OPEN/CLOSE/STOP nodes).
- One node per COBOL statement.
- Grouping, coloring, or ranking by file/path/folder.
- Concatenating programs into one vertical sequence of source order.

REQUIRED:
- Reconstruct the logical architecture: runtime units, named procedures that
  matter, data stores, and business decisions that change control.
- A monolith in one .cbl still explodes into paragraph + data + decision nodes.
- CALL/PERFORM is an edge to the callee in THIS same graph.
- Labels = business English ("Lookup account", "Flag AML if over threshold").
- Color meaning is node kind, never the source file.
- evidence = file:line only (not a swimlane).
- At most ~30 nodes. rank = dependency wave (0 = entries). seq = order in wave.

Kinds: program | paragraph | data | external | decision | start | end
Edges: call | perform | next | loop | reads | writes | yes | no

Origin: __SOURCE_DIR__
Inventory (hints only, verify in source): __INVENTORY__

JSON only:
{"schema":2,"generated_by":"agent","nodes":[{"id":"pgm:LOOKUP","label":"Lookup account","kind":"program","rank":0,"seq":0,"evidence":["src/account_lookup.cbl:22"]}],"edges":[{"source":"pgm:LOOKUP","target":"dat:ACCOUNTS","kind":"reads"}]}
""".replace("__SOURCE_DIR__", str(source_dir)).replace("__INVENTORY__", inventory)
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p", prompt, "--output-format", "json", "--max-turns", "16",
        "--dangerously-skip-permissions", "--allowedTools", "Read,Grep,Glob",
        "--disallowedTools", "Bash,Write", "--add-dir", str(source_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=_claude_code_env(), cwd=str(source_dir),
    )
    _ACTIVE_HEADLESS_PROCS.add(proc)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HeadlessInvocationError("relation-graph agent timed out")
    finally:
        _ACTIVE_HEADLESS_PROCS.discard(proc)
    latency_ms = int((time.monotonic() - t0) * 1000)
    try:
        envelope = json.loads(stdout.decode(errors="replace"))
    except json.JSONDecodeError as extra:
        raise HeadlessInvocationError("relation-graph agent envelope is not JSON") from extra
    cost, inp, out = _cost_from_envelope(envelope)
    if proc.returncode != 0 or envelope.get("is_error"):
        raise HeadlessInvocationError(
            f"relation-graph agent failed: {(envelope.get('result') or stderr.decode(errors='replace'))[:300]}",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    result = str(envelope.get("result", ""))
    start, end = result.find("{"), result.rfind("}")
    try:
        payload = json.loads(result[start:end + 1])
    except (json.JSONDecodeError, ValueError) as extra:
        raise HeadlessInvocationError(
            "relation-graph agent result is not JSON",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        ) from extra
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
        raise HeadlessInvocationError(
            "relation-graph agent result missing nodes",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    payload["generated_by"] = "agent"
    return payload, {
        "cost_usd": cost, "input_tokens": inp, "output_tokens": out,
        "latency_ms": latency_ms, "ok": bool(payload.get("nodes")), "reason": "",
    }


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
- If two DIFFERENT already-generated types share the same simple name (e.g.
  two unrelated work items each declare their own `AccountRecord`, one under
  `...UseCases.AccountLookup` with a `Name` property, another under
  `...UseCases.TransactionPosting` with an `AccountName` property instead) —
  a real CS0117 this session — do not assume they have the same property
  names just because the type name matches. When writing an adapter that
  must satisfy MULTIPLE interfaces with same-named-but-different types,
  check each interface's own (already generated) declaration above for its
  own exact property names before constructing that specific type.
- Same issue, different symptom — a real CS0104/CS0738 this session: a `Cli`
  file with `using` directives pulling in two different
  `...Application.UseCases.*` namespaces that BOTH declare a type with the
  same simple name (e.g. `AccountLookup.AccountRecord` and
  `TransactionPosting.AccountRecord`, each a legitimate separate type). If
  this file references that simple name bare (`AccountRecord`), the compiler
  reports it ambiguous, and any interface member typed with it silently
  fails to implement (CS0738) because the wrong one got picked. Whenever a
  file `using`s more than one `Application.UseCases.*` namespace, check
  whether any type name repeats across them — if so, ALWAYS reference every
  use of that name fully qualified (`CobolBankingSystems.Application.UseCases.
  AccountLookup.AccountRecord`) or via an explicit `using X = Full.Namespace.
  Type;` alias. Never rely on the bare simple name in that situation, even
  if only one of the two types is actually used in a given method.
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
        env=_claude_code_env(),
        cwd=str(out_dir),
    )
    _ACTIVE_HEADLESS_PROCS.add(proc)
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


# Added 2026-09-16 after a Codex audit flagged that our static pre-build
# collision scan (orchestrator.detect_type_name_collisions) was reusing
# _REPAIR_PROMPT — written for a real dotnet CS0234 alias-collision pattern
# with its own worked example — which could steer this repair toward the
# WRONG fix (renaming a nonexistent using-alias) instead of the actual
# problem: a bare reference to a type name declared in two different
# namespaces. Dedicated prompt, matching the diagnostic this scan actually
# emits (see orchestrator.detect_type_name_collisions's return string).
_TYPE_COLLISION_REPAIR_PROMPT = """A static pre-build scan (not dotnet — this is
faster and runs first) found that a C# file references a type name by its bare
simple name, but that same simple name is declared in TWO different
`Application.UseCases.*` namespaces as two separate, legitimate types (e.g.
`AccountLookup.AccountRecord` and `TransactionPosting.AccountRecord`, each
with its own fields — do not merge or delete either type, they are correct
as-is). Fix ONLY the ambiguous references: qualify each one with its FULL
namespace path starting from the root (e.g.
`CobolBankingSystems.Application.UseCases.AccountLookup.AccountRecord`), or
add a `using X = Full.Namespace.Type;` alias at the top of the file — never
rename or remove either colliding type itself.

CRITICAL — a real mistake seen before: do NOT write a PARTIAL/relative
qualifier like `AccountLookup.AccountRecord`. Even with
`using CobolBankingSystems.Application.UseCases.AccountLookup;` at the top of
the file, `AccountLookup` alone is not a resolvable namespace segment from
this file's own namespace (e.g. `CobolBankingSystems.Cli`) — that produces
CS0246 "the type or namespace name 'AccountLookup' could not be found". Only
the FULL dotted path from the global root, or a `using` alias, actually
resolves.

Diagnostic:
{errors}

Write tool only. JSON when done: {{"files_written": ["<path>", ...], "fixed": true}}
"""


async def repair_type_collision(target_dir: Path, errors: str, timeout_s: int = _TIMEOUT_S,
                                on_progress=None) -> ConversionResult:
    return await repair_csharp(target_dir, errors, timeout_s, on_progress, prompt_template=_TYPE_COLLISION_REPAIR_PROMPT)


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
        env=_claude_code_env(),
        cwd=str(target_dir),
    )
    _ACTIVE_HEADLESS_PROCS.add(proc)
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

README.md (solution root) — a NUMBERED step-by-step list (1. 2. 3. ...) for
how to `dotnet build`, `dotnet test`, and run the CLI — never prose
paragraphs for these steps, a reader must be able to follow them in order
without re-reading. Prerequisites section must include REAL install
commands for .NET 8 SDK per OS — never just name "the .NET 8 SDK" as a bare
assumed prerequisite with no install step, a reader without it must be able
to get it from this file alone.

CRITICAL — verified live 2026-09-16: on Ubuntu/Debian, `sudo apt install
dotnet-sdk-8.0` can install a BROKEN package (missing libhostfxr.so — `dotnet
--version` fails with "Failed to resolve libhostfxr.so"). Do NOT recommend
apt as the primary Linux install method. Instead, for Linux (and as the
universal fallback for any OS), tell the reader to use Microsoft's own
install script, which does not have this failure mode:
```
curl -sSL https://dot.net/v1/dotnet-install.sh -o dotnet-install.sh
chmod +x dotnet-install.sh
./dotnet-install.sh --channel 8.0 --install-dir "$HOME/.dotnet"
export PATH="$HOME/.dotnet:$PATH"
```
List this Linux method FIRST, `brew install --cask dotnet-sdk` for macOS,
`winget install Microsoft.DotNet.SDK.8` for Windows — and note that if `apt`
was used and `dotnet --version` fails with a libhostfxr error, the fix is to
run the script above instead (do not try to repair the apt package). After
the install script, add ONE more step: `sudo ln -sf "$HOME/.dotnet/dotnet"
/usr/local/bin/dotnet` — this makes `dotnet` resolve correctly in every new
terminal with zero `export`/`.bashrc` editing required (verified: on a
standard Linux PATH, `/usr/local/bin` is searched before `/usr/bin`, so this
symlink alone shadows a broken system package permanently). Mention that an
already-open shell may need `hash -r` to pick up the new symlink.

CRITICAL — verified live 2026-09-16 (real user friction: "queda mal en vivo"
when a generated CLI reported ACCOUNT NOT FOUND / file-not-found because no
data existed): if ANY work item's CLI reads a data file (accounts.dat,
transactions.dat, or similar fixed-width/line-sequential file — check the
existing tree and any Infrastructure/Persistence source for `File.Exists`,
`ReadAllLines`, `PIC` layout constants), the README's "Run the CLI" section
MUST include a real, runnable snippet that creates a minimal valid sample of
that file BEFORE the run steps — derive the exact field widths from the
actual persistence code in the tree (e.g. a `python3 -c "..."` one-liner
writing a fixed-width line matching the real `AccountNumberDigits`/
`NameLength`/`BalanceDigits` constants). Never leave "you'll need a data
file" unstated — a reader with zero access to the COBOL source or this
codebase's persistence internals must be able to test the FOUND/success path
from this README alone, not just confirm NOT_FOUND on an empty run.
docs/MIGRATION.md — COBOL→C# decisions, traceability (each handler ← COBOL
PROGRAM-ID), limitations. English, dense, factual.

Existing tree:
{tree}

Write tool only. JSON: {{"files_written": ["README.md", "docs/MIGRATION.md"]}}
"""

# Pre-migration documentation is a separate product from migration
# documentation.  The agent receives the legacy estate, an output directory,
# the approved local reference package, and the project's closure criteria.
# It is explicitly prohibited from inventing a TO-BE design or writing C#.
_EXPLORATION_DOC_FILES = [
    "README.md",
    "documentation_graph.json",
    "00-trazabilidad/esquema-de-ids.md",
    "00-trazabilidad/registro-trazabilidad.csv",
    "01-funcional/01-catalogo-de-reglas-de-negocio.md",
    "01-funcional/02-procesos-y-casos-de-uso.md",
    "01-funcional/03-glosario-de-negocio.md",
    "01-funcional/04-preguntas-abiertas.md",
    "02-tecnico/05-inventario-y-catalogo-de-programas.md",
    "02-tecnico/06-diccionario-de-datos.md",
    "02-tecnico/07-mapa-de-dependencias.md",
    "02-tecnico/08-inventario-de-integraciones.md",
    "02-tecnico/09-catalogo-de-procesos-batch.md",
    "02-tecnico/10-diagramas-as-is.md",
    "02-tecnico/11-evaluacion-de-complejidad-y-riesgo.md",
]

_EXPLORATION_DOCS_PROMPT = """Produce the complete PRE-MIGRATION / AS-IS
COBOL documentation dossier. This is exploration and documentation only:
DO NOT create C#, architecture TO-BE, OpenAPI, mappings, plans, tests, or any
other migration output.

Read the complete input estate in LEGACY_SOURCE, the closure criteria in GUIDE, and
the formatting/reference package in REFERENCE_PACKAGE before writing. Use the
same directory and document naming convention as the reference package.

Write exactly these files under OUTPUT_DIR, and no others:
{expected}

Non-negotiable evidence contract:
- Every claim about existing COBOL behavior must cite `file:line` or
  `file:start-end`; do not fabricate runtime observations.
- Distinguish direct code evidence from inference. Mark unverified statements
  as candidates and send uncertainty to preguntas abiertas.
- The CSV is the source of truth: stable IDs (PGM-, DAT-, UC-, BR-, RSK-, QA-)
  with source file/range, verification method, validation status, and empty
  TO-BE fields. All IDs used by Markdown must exist in that CSV.
- Explicitly document both present and searched-but-absent artifacts
  (copybooks, FILE SECTION, SQL, CICS, MQ, FTP, REST/SOAP, CL/JCL, batch).
- Inventory every supplied file, including frontend, design, configuration,
  scripts and documents. They are AS-IS evidence even when they are outside
  the future backend migration scope; label that scope instead of omitting it.
- Diagrams must be Mermaid text and trace their nodes/edges to source.
- Never silently invent a business intent from a technical construct.
- `documentation_graph.json` is a JSON object with `nodes` and `edges`.
  Each node has `id`, `label`, `kind` (`program|rule|risk|question|document`),
  `x`, `y`, and optional `evidence`. Each edge has `source`, `target`, `kind`,
  and optional `evidence`. Place nodes deliberately to explain semantic
  relationships; do not emit a generic linear flow.

LEGACY_SOURCE: {source_dir}
OUTPUT_DIR: {output_dir}
GUIDE: {guide_path}
REFERENCE_PACKAGE: {reference_dir}

Use Read and Write tools only. Return JSON only when finished:
{{"files_written": ["<relative path>", ...]}}
"""


async def write_exploration_docs(
    source_dir: Path, output_dir: Path, guide_path: Path, reference_dir: Path,
    timeout_s: int = 600, on_progress=None,
) -> ConversionResult:
    """Run the same authenticated Claude Code engine used by migration.

    The process may read source and reference material but may write only in
    the run-owned output directory. The deterministic renderer establishes a
    recoverable skeleton first; this agent enriches it with code-grounded
    analysis and the final documentation prose.
    """
    claude_bin = find_claude()
    if claude_bin is None:
        raise HeadlessInvocationError("claude CLI not found")
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt = _EXPLORATION_DOCS_PROMPT.format(
        expected="\n".join(f"- {path}" for path in _EXPLORATION_DOC_FILES),
        source_dir=source_dir,
        output_dir=output_dir,
        guide_path=guide_path,
        reference_dir=reference_dir,
    )
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        claude_bin, "-p", prompt,
        "--output-format", "stream-json", "--verbose", "--max-turns", "24",
        "--dangerously-skip-permissions", "--allowedTools", "Read,Write",
        "--disallowedTools", "Bash", "--add-dir", str(source_dir),
        "--add-dir", str(output_dir), "--add-dir", str(guide_path.parent),
        "--add-dir", str(reference_dir), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_claude_code_env(),
        cwd=str(output_dir),
    )
    _ACTIVE_HEADLESS_PROCS.add(proc)
    envelope: dict | None = None
    stderr_chunks: list[bytes] = []

    async def _drain() -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            stderr_chunks.append(line)

    async def _read() -> None:
        nonlocal envelope
        while True:
            line = await proc.stdout.readline()
            if not line:
                return
            try:
                message = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if message.get("type") == "assistant" and on_progress:
                for block in message.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        on_progress(str(block.get("name")))
            elif message.get("type") == "result":
                envelope = message

    try:
        await asyncio.wait_for(asyncio.gather(_read(), _drain()), timeout=timeout_s)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HeadlessInvocationError(f"exploration documentation timed out after {timeout_s}s")
    await proc.wait()
    latency_ms = int((time.monotonic() - t0) * 1000)
    cost, inp, out = _cost_from_envelope(envelope)
    if envelope is None or envelope.get("is_error") or proc.returncode != 0:
        reason = (envelope or {}).get("result") or b"".join(stderr_chunks).decode(errors="replace")
        raise HeadlessInvocationError(
            f"exploration documentation agent failed: {reason}"[:400],
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    missing = [path for path in _EXPLORATION_DOC_FILES if not (output_dir / path).is_file()]
    if missing:
        raise HeadlessInvocationError(
            f"exploration documentation agent omitted required files: {missing}",
            cost_usd=cost, input_tokens=inp, output_tokens=out, latency_ms=latency_ms,
        )
    return ConversionResult(_EXPLORATION_DOC_FILES, cost, inp, out, latency_ms)


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
        env=_claude_code_env(),
        cwd=str(target_dir),
    )
    _ACTIVE_HEADLESS_PROCS.add(proc)
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
