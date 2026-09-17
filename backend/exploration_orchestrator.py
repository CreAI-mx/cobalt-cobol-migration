"""Exploration Subsystem foreman — parallel per-file structural work."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ulid import ULID

import exploration_core as core
import exploration_documentation
import llm
import parity_gate
from cobol_io_profile import derive_fixture, parse_io_profile
from models import FileEvent, PhaseEvent
from work_items import inventory_source

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"
MAX_STRUCTURAL_PARALLEL = int(os.environ.get("COBALT_EXPLORATION_PARALLEL", "8"))

# Real per-token pricing for claude-sonnet-4-5 — logged to cost_logs so this
# agentic pass is visible in the same spend accounting as every other phase
# (user, verbatim: "quiero que se lleve contabilidad de cuanto lleva gastado").
async def _agentic_business_rules(
    source_dir: Path, member_paths: list[str], draft_rules: list[dict],
) -> tuple[list[dict], dict]:
    """Real Phase 2: one Strands agent call per module, replacing
    exploration_core.draft_business_rules' regex stubs with concrete rules.
    Returns (rules, cost_meta). Falls back to the draft stubs unchanged (with
    a clear reason, never fabricated agent output) if no API key or the call
    fails — exploration must never block on this being unavailable."""
    try:
        rules, cost_meta = await llm.extract_exploration_rules(source_dir, member_paths, draft_rules)
    except llm.HeadlessInvocationError as exc:
        cost_meta = {"cost_usd": exc.cost_usd, "input_tokens": exc.input_tokens, "output_tokens": exc.output_tokens,
                     "latency_ms": exc.latency_ms, "ok": False, "reason": f"Claude Code failed: {exc}"[:200]}
        return draft_rules, cost_meta
    except Exception as exc:
        cost_meta = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                     "latency_ms": 0, "ok": False, "reason": f"Claude Code failed: {exc}"[:200]}
        return draft_rules, cost_meta
    if not rules:
        cost_meta["reason"] = "Claude Code returned no evidence-backed rules — kept deterministic drafts"
        return draft_rules, cost_meta
    return rules, cost_meta


def _relation_graph_path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "exploration" / "estate_relation_graph.json"


async def _agentic_relation_graph(source_dir: Path, pack: dict) -> tuple[dict | None, dict]:
    """Called from execute_exploration. Schema: relation_graph nodes/edges.
    User: un diagrama de relacion secuencia uno solo, construido agenticamente."""
    candidates = {
        "programs": [
            {
                "path": p.get("path"),
                "program_id": p.get("program_id"),
                "paragraphs": p.get("paragraphs"),
                "procedure_edges": p.get("procedure_edges"),
                "call_targets": p.get("call_targets"),
            }
            for p in pack.get("programs") or []
        ],
        "calls": pack.get("call_graph_resolved", {}).get("edges", []),
    }
    try:
        raw, cost_meta = await llm.extract_estate_relation_graph(source_dir, candidates)
    except llm.HeadlessInvocationError as exc:
        return None, {
            "cost_usd": exc.cost_usd, "input_tokens": exc.input_tokens,
            "output_tokens": exc.output_tokens, "latency_ms": exc.latency_ms,
            "ok": False, "reason": f"Claude Code failed: {exc}"[:200],
        }
    except Exception as exc:
        return None, {
            "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
            "ok": False, "reason": f"Claude Code failed: {exc}"[:200],
        }
    graph = core.normalize_relation_graph(raw)
    graph["generated_by"] = "agent"
    if not graph["nodes"]:
        cost_meta["ok"] = False
        cost_meta["reason"] = "agent returned an empty graph"
        return None, cost_meta
    return graph, cost_meta


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run_oracle_baseline(source_dir: Path, cobol_files: list) -> dict:
    """Real ask (user, 2026-09-16): does Cobalt run the ORIGINAL COBOL to
    know what to aspire to before writing C#? Answer was no — the GnuCOBOL
    oracle only ran post-hoc, inside the migration's Parity gate. This runs
    each COBOL program for real (reusing parity_gate's own compile+run
    machinery, no reimplementation) during Exploration instead, so Planning/
    Generating receive real captured behavior as ground truth, not just
    static source text. Returns {path: {"ok": bool, "output": str}}."""
    baseline: dict[str, dict] = {}
    for f in cobol_files:
        cbl_path = source_dir / f.path
        try:
            text = cbl_path.read_text(errors="replace")
            profile = parse_io_profile(text)
            fixture = derive_fixture(profile)
            ok, output = await parity_gate._run_cobol_side(cbl_path, profile, fixture)
            baseline[f.path] = {"ok": ok, "output": output[:2000]}
        except Exception as exc:
            baseline[f.path] = {"ok": False, "output": f"baseline execution failed: {exc}"[:300]}
    return baseline


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
    # Real bug found live 2026-09-16: this used to also set status='REVIEW'
    # and finished_at=now() here — but Business logic, Graph, and
    # Documentation (all real agentic steps) still run AFTER this point.
    # A caller checking exploration_sessions saw "REVIEW, finished" and tried
    # to lock/start migration while the task was still genuinely in flight
    # (lock correctly 409'd since _exploration_is_live() was still True, but
    # the DB row lied about being done). Only persist the draft pack here;
    # status/finished_at are set once, for real, at the true end of this
    # function after every step completes.
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ? WHERE run_id = ?",
        (json.dumps(pack), run_id),
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

    # Real ask (user, 2026-09-16): "real agentico lo de la exploracion,
    # generacion de documentacion... y el diagrama tambien agentico... y lo
    # renderizas estos dos agentes en paralelo". The relation-graph agent and
    # the documentation agent write to independent artifacts (a JSON graph
    # file vs the docs/ tree) and neither reads the other's output, so they
    # are genuinely safe to run concurrently instead of sequentially —
    # wall-clock drops to max(graph, docs) instead of graph + docs.
    events.append(PhaseEvent(
        phase="Exploration · Graph", skill="cobol-relation-graph", status="RUNNING",
        detail="agent constructing one relation + sequence graph",
    ))
    docs_dir = RUNS_DIR / run_id / "docs-cobol-accounting-system" / "docs"
    corpus_dir = docs_dir.parent / "analysis-corpus"
    corpus_stats = exploration_documentation.prepare_repository_corpus(REPO_ROOT, corpus_dir)
    doc_result = exploration_documentation.write_as_is_documentation(docs_dir, corpus_dir, pack)
    graph_path = docs_dir / "documentation_graph.json"
    skeleton_graph = json.loads(graph_path.read_text(encoding="utf-8"))
    pack["documentation"] = {
        "scope": "Complete repository AS-IS exploration only; no TO-BE or migration artifacts",
        "root": str(docs_dir),
        "corpus": corpus_stats,
        "documents": doc_result["documents"],
        "agent_status": "deterministic skeleton",
        "graph": skeleton_graph,
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    events.append(PhaseEvent(
        phase="Exploration · Documentation", skill="as-is-documentation", status="RUNNING",
        detail="building traceable Tier 1 and Tier 2 dossier",
    ))
    # Same bug class as the earlier "Modules" fix, reintroduced at this later
    # point during this refactor — caught live 2026-09-16 re-testing the E2E
    # gate: this must NOT set status='REVIEW' here. The Graph + Documentation
    # agents (below, run concurrently) still have real work in flight; only
    # persist the draft pack, never mark the session done until the true end.
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ? WHERE run_id = ?",
        (json.dumps(pack), run_id),
    )
    await conn.commit()

    events.append(PhaseEvent(
        phase="Exploration · Baseline", skill="cobol-oracle-baseline", status="RUNNING",
        detail="running original COBOL for real to capture expected behavior",
    ))
    reference_dir = REPO_ROOT / "docs-cobol-accounting-system" / "docs"
    guide_path = REPO_ROOT / "GUIA-DOCUMENTACION-MIGRACION-COBOL-CSHARP.md"
    graph_result, docs_result, baseline_result = await asyncio.gather(
        _agentic_relation_graph(source_dir, pack),
        llm.write_exploration_docs(corpus_dir, docs_dir, guide_path, reference_dir),
        _run_oracle_baseline(source_dir, cobol),
        return_exceptions=True,
    )
    if isinstance(baseline_result, Exception):
        events.append(PhaseEvent(
            phase="Exploration · Baseline", skill="cobol-oracle-baseline", status="SKIPPED",
            detail=f"baseline execution failed: {baseline_result}"[:200],
        ))
    else:
        pack["oracle_baseline"] = baseline_result
        ok_count = sum(1 for v in baseline_result.values() if v.get("ok"))
        events.append(PhaseEvent(
            phase="Exploration · Baseline", skill="cobol-oracle-baseline",
            status="OK" if ok_count == len(baseline_result) else "BLOCKED",
            detail=f"{ok_count}/{len(baseline_result)} programs executed for real — captured as Planning input",
        ))

    graph, graph_cost = (None, {"ok": False, "reason": str(graph_result)}) if isinstance(graph_result, Exception) else graph_result
    total_cost += graph_cost.get("cost_usd") or 0.0
    if graph_cost.get("ok") and graph:
        pack["relation_graph"] = graph
        out_path = _relation_graph_path(run_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        await conn.execute(
            "INSERT INTO cost_logs (log_id, run_id, phase, agent_id, input_tokens, "
            "output_tokens, cost_usd, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(ULID()), run_id, "Exploration · Graph", "claude-code-graph",
             graph_cost["input_tokens"], graph_cost["output_tokens"], graph_cost["cost_usd"],
             graph_cost.get("latency_ms") or 0, _now()),
        )
        events.append(PhaseEvent(
            phase="Exploration · Graph", skill="cobol-relation-graph", status="OK",
            detail=f"{len(graph['nodes'])} nodes · {len(graph['edges'])} edges (${graph_cost['cost_usd']:.4f})",
        ))
    else:
        if graph_cost.get("cost_usd"):
            await conn.execute(
                "INSERT INTO cost_logs (log_id, run_id, phase, agent_id, input_tokens, "
                "output_tokens, cost_usd, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(ULID()), run_id, "Exploration · Graph", "claude-code-graph",
                 graph_cost.get("input_tokens") or 0, graph_cost.get("output_tokens") or 0,
                 graph_cost.get("cost_usd") or 0.0, graph_cost.get("latency_ms") or 0, _now()),
            )
        events.append(PhaseEvent(
            phase="Exploration · Graph", skill="cobol-relation-graph", status="SKIPPED",
            detail=graph_cost.get("reason") or "agent did not produce a relation graph",
        ))
        pack.pop("relation_graph", None)
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ? WHERE run_id = ?",
        (json.dumps(pack), run_id),
    )
    await conn.commit()
    if isinstance(docs_result, llm.HeadlessInvocationError):
        await conn.execute(
            "INSERT INTO cost_logs (log_id, run_id, phase, agent_id, input_tokens, "
            "output_tokens, cost_usd, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(ULID()), run_id, "Exploration · Documentation", "claude-code-docs",
             docs_result.input_tokens, docs_result.output_tokens, docs_result.cost_usd, docs_result.latency_ms, _now()),
        )
        pack["documentation"]["agent_status"] = f"skeleton only: {str(docs_result)[:200]}"
        pack["documentation"].update({
            "cost_usd": docs_result.cost_usd, "input_tokens": docs_result.input_tokens,
            "output_tokens": docs_result.output_tokens,
        })
        events.append(PhaseEvent(
            phase="Exploration · Documentation", skill="claude-code-as-is-docs", status="SKIPPED",
            detail=f"Claude Code failed after ${docs_result.cost_usd:.4f}; auditable skeleton retained",
        ))
    elif isinstance(docs_result, Exception):
        pack["documentation"]["agent_status"] = f"skeleton only: {str(docs_result)[:200]}"
        events.append(PhaseEvent(
            phase="Exploration · Documentation", skill="claude-code-as-is-docs", status="SKIPPED",
            detail=f"Claude Code unavailable; auditable skeleton retained: {str(docs_result)[:160]}",
        ))
    else:
        closure_errors = exploration_documentation.validate_as_is_documentation(
            docs_dir, corpus_dir, docs_result.files_written,
        )
        if closure_errors:
            pack["documentation"]["agent_status"] = "skeleton only: documentation closure failed: " + "; ".join(closure_errors[:4])
            events.append(PhaseEvent(
                phase="Exploration · Documentation", skill="claude-code-as-is-docs", status="SKIPPED",
                detail="documentation closure failed: " + "; ".join(closure_errors[:4]),
            ))
        else:
            pack["documentation"].update({
                "documents": docs_result.files_written,
                "agent_status": "Claude Code complete",
                "graph": json.loads(graph_path.read_text(encoding="utf-8")),
                "cost_usd": docs_result.cost_usd,
                "input_tokens": docs_result.input_tokens,
                "output_tokens": docs_result.output_tokens,
            })
            events.append(PhaseEvent(
                phase="Exploration · Documentation", skill="claude-code-as-is-docs", status="OK",
                detail=f"{len(docs_result.files_written)} AS-IS documents written (${docs_result.cost_usd:.4f})",
            ))
        await conn.execute(
            "INSERT INTO cost_logs (log_id, run_id, phase, agent_id, input_tokens, "
            "output_tokens, cost_usd, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(ULID()), run_id, "Exploration · Documentation", "claude-code-docs",
             docs_result.input_tokens, docs_result.output_tokens, docs_result.cost_usd, docs_result.latency_ms, _now()),
        )
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ?, status = ?, finished_at = ? WHERE run_id = ?",
        (json.dumps(pack), "REVIEW", _now(), run_id),
    )
    await conn.commit()
