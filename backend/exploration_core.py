"""Deterministic exploration pipeline: structural parse, dependency graph,
migration-module clustering, ExplorationPack assembly. Agentic Phase 2 layers
on top via exploration_orchestrator (optional LLM)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ulid import ULID

from work_items import (
    CALL_RE,
    PROGRAM_ID_RE,
    connected_cobol_groups,
    inventory_source,
    pascal_stem,
)

DIVISION_RE = re.compile(r"^\s*(\w+(?:\s+\w+)*)\s+DIVISION\s*\.", re.MULTILINE | re.IGNORECASE)
PARAGRAPH_RE = re.compile(r"^\s*([A-Z0-9][A-Z0-9-]*)\.\s*$", re.MULTILINE)
PROCEDURE_RE = re.compile(r"PROCEDURE\s+DIVISION", re.IGNORECASE)
PERFORM_NAMED_RE = re.compile(
    r"\bPERFORM\s+([A-Z0-9][A-Z0-9-]*)(?:\s+THROUGH|\s+THRU\s+([A-Z0-9][A-Z0-9-]*))?",
    re.IGNORECASE,
)
PERFORM_LOOP_RE = re.compile(r"\bPERFORM\s+(UNTIL|VARYING|WITH\s+TEST)\b", re.IGNORECASE)
GOTO_RE = re.compile(r"\bGO\s+TO\s+([A-Z0-9][A-Z0-9-]*)", re.IGNORECASE)
STOP_RE = re.compile(r"\b(STOP\s+RUN|GOBACK|EXIT\s+PROGRAM)\b", re.IGNORECASE)
_RESERVED_PARA = {
    "IDENTIFICATION", "ENVIRONMENT", "DATA", "PROCEDURE", "FILE-CONTROL",
    "FILE", "WORKING-STORAGE", "LINKAGE", "CONFIGURATION", "INPUT-OUTPUT",
    "SPECIAL-NAMES", "SOURCE-COMPUTER", "OBJECT-COMPUTER",
}
PIC_FIELD_RE = re.compile(
    r"^\s*(\d+\s+)?([A-Z0-9][A-Z0-9-]*)\s+PIC\s+([^.]+)\.",
    re.MULTILINE | re.IGNORECASE,
)
COMP3_RE = re.compile(r"COMP-3|PACKED-DECIMAL", re.IGNORECASE)
REDEFINES_RE = re.compile(r"\bREDEFINES\b", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _complexity_tier(text: str, variables: list[dict]) -> str:
    if REDEFINES_RE.search(text) or "OCCURS DEPENDING" in text.upper():
        return "HIGH"
    if COMP3_RE.search(text) or any("COMP-3" in v.get("pic", "").upper() for v in variables):
        return "MEDIUM"
    return "LOW"


def parse_structural(text: str) -> dict[str, Any]:
    divisions = sorted({m.group(1).upper().replace("  ", " ") for m in DIVISION_RE.finditer(text)})
    variables: list[dict] = []
    for m in PIC_FIELD_RE.finditer(text):
        name, pic = m.group(2), m.group(3).strip()
        tag = []
        if COMP3_RE.search(pic):
            tag.append("COMP-3")
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start : line_end if line_end != -1 else len(text)]
        if REDEFINES_RE.search(line):
            tag.append("REDEFINES")
        variables.append({"name": name, "pic": pic, "tags": tag})
    paragraphs, procedure_edges = procedure_flow(text)
    calls = CALL_RE.findall(text)
    pid_m = PROGRAM_ID_RE.search(text)
    program_id = pid_m.group(1) if pid_m else None
    return {
        "program_id": program_id,
        "divisions": divisions,
        "variables_json": variables,
        "paragraphs_json": paragraphs,
        "procedure_edges": procedure_edges,
        "calls": calls,
        "complexity_tier": _complexity_tier(text, variables),
    }



def _procedure_section(text: str) -> str:
    m = PROCEDURE_RE.search(text)
    return text[m.end():] if m else ""


def procedure_flow(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Named paragraphs after PROCEDURE DIVISION plus PERFORM/GO TO/loop edges."""
    proc = _procedure_section(text)
    if not proc.strip():
        return [], []
    blocks: list[tuple[str, str]] = []
    current = "PROCEDURE"
    buf: list[str] = []
    for line in proc.splitlines():
        hm = PARAGRAPH_RE.match(line)
        name = hm.group(1).upper() if hm else ""
        if hm and name not in _RESERVED_PARA and name not in {"STOP", "EXIT", "CONTINUE", "GOBACK"}:
            blocks.append((current, "\n".join(buf)))
            current = name
            buf = []
        else:
            buf.append(line)
    blocks.append((current, "\n".join(buf)))
    ordered: list[str] = []
    for n, _ in blocks:
        if n not in ordered:
            ordered.append(n)
    if ordered == ["PROCEDURE"] and not blocks[0][1].strip():
        return [], []
    edges: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(src: str, dst: str, kind: str) -> None:
        key = (src, dst, kind)
        if key in seen:
            return
        seen.add(key)
        edges.append({"from": src, "to": dst, "kind": kind})

    para_set = {n for n, _ in blocks}
    for i, (src, body) in enumerate(blocks):
        if PERFORM_LOOP_RE.search(body):
            add(src, src, "loop")
        for m in PERFORM_NAMED_RE.finditer(body):
            target = m.group(1).upper()
            if target in {"UNTIL", "VARYING", "WITH", "TEST"}:
                continue
            if target in para_set:
                add(src, target, "perform")
            thru = m.group(2)
            if thru and thru.upper() in para_set:
                add(src, thru.upper(), "thru")
        for m in GOTO_RE.finditer(body):
            dest = m.group(1).upper()
            if dest in para_set:
                add(src, dest, "goto")
        if i + 1 < len(blocks) and not STOP_RE.search(body):
            nxt = blocks[i + 1][0]
            if nxt != src:
                add(src, nxt, "next")
    return ordered, edges


def build_graph_edges(files) -> tuple[list[dict], list[str]]:
    pid_to_path = {f.program_id.upper(): f.path for f in files if f.program_id}
    edges: list[dict] = []
    open_items: list[str] = []
    seen: set[tuple[str, str]] = set()
    for f in files:
        if f.kind != "cobol_source":
            continue
        for target in f.calls:
            tid = target.upper()
            to_path = pid_to_path.get(tid)
            if not to_path:
                open_items.append(
                    f"Unresolved CALL '{target}' from {f.path} — no PROGRAM-ID match in estate"
                )
                continue
            key = (f.path, to_path)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from_path": f.path,
                    "to_path": to_path,
                    "edge_type": "CALL",
                    "target_program_id": target,
                }
            )
    return edges, open_items


def modules_from_groups(groups, sln: str) -> list[dict]:
    modules: list[dict] = []
    for i, group in enumerate(groups, start=1):
        paths = [f.path for f in group]
        pids = [f.program_id for f in group if f.program_id]
        path_set = {f.path for f in group}
        pid_by_path = {f.path: (f.program_id or "").upper() for f in group}
        targets_in = set()
        for f in group:
            for t in f.calls:
                for g in group:
                    if g.program_id and g.program_id.upper() == t.upper():
                        targets_in.add(g.path)
        roots = [f for f in group if f.path not in targets_in]
        entry = sorted(roots, key=lambda x: x.path)[0] if roots else sorted(group, key=lambda x: x.path)[0]
        title_parts = [pascal_stem(f.program_id or Path(f.path).stem) for f in group]
        title = title_parts[0] if len(title_parts) == 1 else " + ".join(title_parts[:3])
        suggested = []
        for f in group:
            name = pascal_stem(f.program_id or Path(f.path).stem)
            suggested.append(f"src/Application/UseCases/{name}/")
        modules.append(
            {
                "module_id": f"mod-{i:03d}",
                "title": title,
                "source_program_ids": pids,
                "member_paths": paths,
                "entrypoint_program_id": entry.program_id,
                "entrypoint_path": entry.path,
                "conversion_order_hint": i,
                "suggested_target_projects": suggested,
                "business_rules": [],
                "risks": [],
                "human_notes": "",
            }
        )
    return modules


def draft_business_rules(struct: dict, path: str) -> list[dict]:
    rules: list[dict] = []
    for para in struct.get("paragraphs_json", [])[:12]:
        rules.append(
            {
                "id": f"BR-{para}",
                "text": f"Review paragraph {para} for business behavior (draft — confirm or replace via agent).",
                "anchors": [f"{path}:{para}"],
                "source": "deterministic_draft",
            }
        )
    seen_calls: set[str] = set()
    for call in struct.get("calls", []):
        if call in seen_calls:
            continue
        seen_calls.add(call)
        rules.append(
            {
                "id": f"BR-CALL-{call}",
                "text": f"Invokes program {call} — verify linkage and side effects at migration time.",
                "anchors": [f"{path}:CALL '{call}'"],
                "source": "deterministic_draft",
            }
        )
    return rules


def build_exploration_pack(
    run_id: str,
    source_dir: Path,
    *,
    locked: bool = False,
    human_notes_by_module: dict[str, str] | None = None,
) -> dict[str, Any]:
    files = inventory_source(source_dir)
    cobol = [f for f in files if f.kind == "cobol_source"]
    copybooks = [f for f in files if f.kind == "copybook"]
    edges, open_items = build_graph_edges(cobol)
    groups = connected_cobol_groups(files)
    modules = modules_from_groups(groups, source_dir.name)
    notes = human_notes_by_module or {}
    for mod in modules:
        mod["human_notes"] = notes.get(mod["module_id"], "")
        paths = set(mod["member_paths"])
        mod_risks: list[str] = []
        mod_rules: list[dict] = []
        for f in cobol:
            if f.path not in paths:
                continue
            text = (source_dir / f.path).read_text(errors="replace")
            struct = parse_structural(text)
            if struct["complexity_tier"] == "HIGH":
                mod_risks.append(f"HIGH complexity: {f.path}")
            for v in struct["variables_json"]:
                if "COMP-3" in v.get("tags", []):
                    mod_risks.append(f"COMP-3 field {v['name']} in {f.path}")
                if "REDEFINES" in v.get("tags", []):
                    mod_risks.append(f"REDEFINES on {v['name']} in {f.path}")
            mod_rules.extend(draft_business_rules(struct, f.path))
        mod["business_rules"] = mod_rules
        mod["risks"] = sorted(set(mod_risks))

    path_to_module: dict[str, str] = {}
    for mod in modules:
        for p in mod["member_paths"]:
            path_to_module[p] = mod["module_id"]
    programs_catalog: list[dict] = []
    data_dictionary: list[dict] = []
    for f in cobol:
        text = (source_dir / f.path).read_text(errors="replace")
        struct = parse_structural(text)
        for v in struct["variables_json"]:
            data_dictionary.append({
                "name": v.get("name", "—"),
                "pic": v.get("pic", "—"),
                "tags": v.get("tags", []),
                "path": f.path,
            })
        programs_catalog.append(
            {
                "path": f.path,
                "program_id": f.program_id or struct.get("program_id"),
                "module_id": path_to_module.get(f.path),
                "complexity_tier": struct["complexity_tier"],
                "paragraphs": struct["paragraphs_json"][:48],
                "procedure_edges": struct.get("procedure_edges", []),
                "call_targets": list(dict.fromkeys(struct["calls"])),
                "loc": f.loc,
            }
        )

    topo = [e["from_path"] for e in edges]
    return {
        "exploration_pack_schema": 1,
        "run_id": run_id,
        "locked_at": _now() if locked else None,
        "inventory_summary": {
            "files": len(files),
            "programs": len(cobol),
            "copybooks": len(copybooks),
        },
        "modules": modules,
        "programs": programs_catalog,
        "data_dictionary": data_dictionary,
        "call_graph_resolved": {"edges": edges, "topological_order": topo},
        "open_items": [{"id": str(ULID()), "text": t, "status": "open"} for t in open_items],
        "planner_seed": {
            "work_item_hints": [
                {
                    "kind": "conversion",
                    "title": m["title"],
                    "source_paths": m["member_paths"],
                    "wave": m["conversion_order_hint"] - 1,
                }
                for m in modules
            ],
            "directive_fragments": [
                "Preserve CALL graph boundaries as migration modules unless architecture workshop overrides.",
            ],
        },
    }
