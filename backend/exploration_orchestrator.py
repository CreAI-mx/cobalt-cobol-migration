"""Exploration Subsystem foreman — parallel per-file structural work."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ulid import ULID

import exploration_core as core
from models import FileEvent, PhaseEvent
from work_items import inventory_source

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"
MAX_STRUCTURAL_PARALLEL = int(os.environ.get("COBALT_EXPLORATION_PARALLEL", "8"))

# Real per-token pricing for claude-sonnet-4-5 — logged to cost_logs so this
# agentic pass is visible in the same spend accounting as every other phase
# (user, verbatim: "quiero que se lleve contabilidad de cuanto lleva gastado").
_PRICE_IN_PER_MTOK = 3.00
_PRICE_OUT_PER_MTOK = 15.00
_BUSINESS_RULES_MAX_TOKENS = 2000

_AGENTIC_RULES_PROMPT = """You extract REAL business rules from this COBOL module,
replacing the draft stubs below with concrete, specific rules — cite the exact
paragraph or CALL site for each. Return ONLY a JSON array, no prose:
[{{"id": "BR-...", "text": "<specific business rule, plain language>",
"anchors": ["<file>:<paragraph or statement>"], "source": "agent"}}]

Draft stubs (for context on what paragraphs/calls exist — replace, don't just repeat):
{drafts}

COBOL source:
{source}
"""


async def _agentic_business_rules(
    source_dir: Path, member_paths: list[str], draft_rules: list[dict],
) -> tuple[list[dict], dict]:
    """Real Phase 2: one Strands agent call per module, replacing
    exploration_core.draft_business_rules' regex stubs with concrete rules.
    Returns (rules, cost_meta). Falls back to the draft stubs unchanged (with
    a clear reason, never fabricated agent output) if no API key or the call
    fails — exploration must never block on this being unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    cost_meta = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "ok": False, "reason": ""}
    if not api_key:
        cost_meta["reason"] = "ANTHROPIC_API_KEY not set — kept deterministic drafts"
        return draft_rules, cost_meta

    from strands import Agent
    from strands.models.anthropic import AnthropicModel

    source_blob = "\n\n".join(
        f"--- {p} ---\n{(source_dir / p).read_text(errors='replace')[:6000]}"
        for p in member_paths
    )
    prompt = _AGENTIC_RULES_PROMPT.format(
        drafts=json.dumps(draft_rules), source=source_blob[:16000],
    )

    def _call_sync():
        model = AnthropicModel(
            client_args={"api_key": api_key},
            model_id="claude-sonnet-4-5-20250929",
            max_tokens=_BUSINESS_RULES_MAX_TOKENS,
        )
        agent = Agent(model=model, tools=[])
        return agent(prompt)

    try:
        result = await asyncio.to_thread(_call_sync)
    except Exception as exc:
        cost_meta["reason"] = f"agent call failed: {exc}"[:200]
        return draft_rules, cost_meta

    usage = dict(result.metrics.accumulated_usage) if getattr(result, "metrics", None) else {}
    inp = usage.get("inputTokens", usage.get("input_tokens", 0))
    out = usage.get("outputTokens", usage.get("output_tokens", 0))
    cost_meta.update({
        "input_tokens": inp, "output_tokens": out,
        "cost_usd": inp / 1_000_000 * _PRICE_IN_PER_MTOK + out / 1_000_000 * _PRICE_OUT_PER_MTOK,
    })

    text = str(result)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        cost_meta["reason"] = "agent did not return a JSON array — kept deterministic drafts"
        return draft_rules, cost_meta
    try:
        rules = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        cost_meta["reason"] = "agent JSON parse failed — kept deterministic drafts"
        return draft_rules, cost_meta
    if not isinstance(rules, list) or not rules:
        cost_meta["reason"] = "agent returned no rules — kept deterministic drafts"
        return draft_rules, cost_meta
    cost_meta["ok"] = True
    return rules, cost_meta


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _set_session(conn, run_id: str, status: str, **extra: str) -> None:
    cols = ["status = ?"]
    vals: list = [status]
    for k, v in extra.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(run_id)
    await conn.execute(
        f"UPDATE exploration_sessions SET {', '.join(cols)} WHERE run_id = ?",
        vals,
    )
    await conn.commit()


async def _load_cobol_file_rows(conn, run_id: str):
    cur = await conn.execute(
        "SELECT file_id, path, program_id, loc, sha256, file_kind "
        "FROM cobol_files WHERE run_id = ? AND file_kind = 'cobol_source' ORDER BY path",
        (run_id,),
    )
    return await cur.fetchall()


async def execute_exploration(run_id: str, conn, events: list) -> None:
    source_dir = RUNS_DIR / run_id / "source"
    if not source_dir.is_dir():
        events.append(PhaseEvent(
            phase="Exploration · Discovery", skill="cobol-discovery", status="BLOCKED",
            detail="source directory missing — run intake first",
        ))
        await _set_session(conn, run_id, "FAILED", finished_at=_now())
        return

    await _set_session(conn, run_id, "RUNNING", started_at=_now(), finished_at="")
    await conn.execute("DELETE FROM cobol_analyses WHERE run_id = ?", (run_id,))
    await conn.execute("DELETE FROM dependency_edges WHERE run_id = ?", (run_id,))
    await conn.commit()

    events.append(PhaseEvent(
        phase="Exploration · Discovery", skill="cobol-discovery", status="OK",
        detail="intake inventory already on disk — using cobol_files rows",
    ))

    rows = await _load_cobol_file_rows(conn, run_id)
    total = len(rows)
    events.append(PhaseEvent(
        phase="Exploration · Structural", skill="cobol-structural-analysis", status="RUNNING",
        detail=f"0/{total} programs parsed",
    ))

    sem = asyncio.Semaphore(MAX_STRUCTURAL_PARALLEL)
    done_count = 0
    lock = asyncio.Lock()

    async def one_file(row: tuple) -> None:
        nonlocal done_count
        file_id, path, program_id, loc, sha256, _kind = row
        events.append(FileEvent(
            run_id=run_id, phase="Exploration · Structural", file_path=path,
            status="RUNNING", detail="parsing divisions, PIC, paragraphs",
        ))
        text = (source_dir / path).read_text(errors="replace")
        struct = core.parse_structural(text)
        async with sem:
            await conn.execute(
                "INSERT INTO cobol_analyses "
                "(analysis_id, run_id, file_id, divisions_json, variables_json, "
                "paragraphs_json, complexity_tier, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(ULID()), run_id, file_id,
                    json.dumps(struct["divisions"]),
                    json.dumps(struct["variables_json"]),
                    json.dumps(struct["paragraphs_json"]),
                    struct["complexity_tier"],
                    _now(),
                ),
            )
            await conn.commit()
        events.append(FileEvent(
            run_id=run_id, phase="Exploration · Structural", file_path=path,
            status="OK",
            detail=f"{struct['complexity_tier']} · {len(struct['paragraphs_json'])} paragraphs · "
                   f"{len(struct['calls'])} CALL sites",
        ))
        async with lock:
            done_count += 1
            events.append(PhaseEvent(
                phase="Exploration · Structural", skill="cobol-structural-analysis", status="RUNNING",
                detail=f"{done_count}/{total} programs parsed",
            ))

    if rows:
        await asyncio.gather(*(one_file(r) for r in rows))
    events.append(PhaseEvent(
        phase="Exploration · Structural", skill="cobol-structural-analysis", status="OK",
        detail=f"{total}/{total} programs parsed",
    ))

    events.append(PhaseEvent(
        phase="Exploration · Dependency", skill="cobol-dependency-mapping", status="RUNNING",
        detail="resolving CALL edges",
    ))
    files = inventory_source(source_dir)
    cobol = [f for f in files if f.kind == "cobol_source"]
    path_to_id = {r[1]: r[0] for r in rows}
    edges, open_items = core.build_graph_edges(cobol)
    for e in edges:
        fid = path_to_id.get(e["from_path"])
        tid = path_to_id.get(e["to_path"])
        if fid and tid:
            await conn.execute(
                "INSERT INTO dependency_edges (edge_id, run_id, from_file_id, to_file_id, edge_type) "
                "VALUES (?,?,?,?,?)",
                (str(ULID()), run_id, fid, tid, e["edge_type"]),
            )
    await conn.commit()
    detail = f"{len(edges)} CALL edges"
    if open_items:
        detail += f" · {len(open_items)} unresolved"
    events.append(PhaseEvent(
        phase="Exploration · Dependency", skill="cobol-dependency-mapping",
        status="OK" if not open_items else "BLOCKED",
        detail=detail,
    ))

    events.append(PhaseEvent(
        phase="Exploration · Modules", skill="migration-module-synthesis", status="RUNNING",
        detail="clustering programs by CALL connectivity",
    ))
    pack = core.build_exploration_pack(run_id, source_dir, locked=False)
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ?, status = ?, finished_at = ? WHERE run_id = ?",
        (json.dumps(pack), "REVIEW", _now(), run_id),
    )
    await conn.commit()
    mod_count = len(pack.get("modules", []))
    events.append(PhaseEvent(
        phase="Exploration · Modules", skill="migration-module-synthesis", status="OK",
        detail=f"{mod_count} migration module(s) · pack draft ready",
    ))

    events.append(PhaseEvent(
        phase="Exploration · Business logic", skill="cobol-business-logic-extraction",
        status="RUNNING", detail=f"replacing draft stubs with real agent extraction ({mod_count} module(s))",
    ))
    total_cost = 0.0
    any_ok = False
    for mod in pack.get("modules", []):
        rules, cost_meta = await _agentic_business_rules(
            source_dir, mod.get("member_paths", []), mod.get("business_rules", []),
        )
        mod["business_rules"] = rules
        total_cost += cost_meta["cost_usd"]
        if cost_meta["ok"]:
            any_ok = True
            await conn.execute(
                "INSERT INTO cost_logs (log_id, run_id, phase, agent_id, input_tokens, "
                "output_tokens, cost_usd, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(ULID()), run_id, "Exploration · Business logic", "strands-agent",
                 cost_meta["input_tokens"], cost_meta["output_tokens"], cost_meta["cost_usd"], 0, _now()),
            )
        events.append(PhaseEvent(
            phase="Exploration · Business logic", skill="cobol-business-logic-extraction",
            status="OK" if cost_meta["ok"] else "SKIPPED",
            detail=(f"{mod.get('title', mod.get('module_id'))}: {len(rules)} rules from agent "
                    f"(${cost_meta['cost_usd']:.4f})" if cost_meta["ok"]
                    else f"{mod.get('title', mod.get('module_id'))}: {cost_meta['reason']}"),
        ))
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ? WHERE run_id = ?",
        (json.dumps(pack), run_id),
    )
    await conn.commit()
    events.append(PhaseEvent(
        phase="Exploration · Business logic", skill="cobol-business-logic-extraction",
        status="OK" if any_ok else "SKIPPED",
        detail=f"total agent cost ${total_cost:.4f}" if any_ok else "no agent extraction ran — drafts kept",
    ))
