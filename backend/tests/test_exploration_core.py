from pathlib import Path

from exploration_core import (
    build_exploration_pack,
    parse_structural,
    procedure_flow,
    normalize_relation_graph,
    procedure_flowchart,
    estate_logic_flowchart,
    is_flowchart_graph,
    compress_flowchart,
    flowchart_to_mermaid,
)


BANKING = Path("/home/frg/creai/cobol/migration-state/runs/01M2NH7YT3KB7X4NX9RNWRKG00/source/cobol-banking-systems/src")


def test_parse_structural_finds_program_and_call():
    text = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPROG.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'DATAPROG'.
       STOP RUN.
"""
    s = parse_structural(text)
    assert s["program_id"] == "MAINPROG"
    assert "MAIN-PARA" in s["paragraphs_json"]
    assert s["calls"] == ["DATAPROG"]


def test_build_pack_groups_connected_programs(tmp_path: Path):
    (tmp_path / "main.cob").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. MAINPROG.\nPROCEDURE DIVISION.\n"
        "A.\nCALL 'CHILD'.\n",
        encoding="utf-8",
    )
    (tmp_path / "child.cob").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. CHILD.\nPROCEDURE DIVISION.\nB.\n",
        encoding="utf-8",
    )
    pack = build_exploration_pack("run-test", tmp_path)
    assert pack["inventory_summary"]["programs"] == 2
    assert len(pack["modules"]) == 1
    assert len(pack["call_graph_resolved"]["edges"]) == 1


def test_paragraphs_are_procedure_only():
    text = (BANKING / "account_lookup.cbl").read_text()
    s = parse_structural(text)
    assert "FILE-CONTROL" not in s["paragraphs_json"]
    kinds = {e["kind"] for e in s["procedure_edges"]}
    assert "loop" in kinds


def test_perform_named_paragraph():
    text = (BANKING / "transaction_posting.cbl").read_text()
    names, edges = procedure_flow(text)
    assert "PROCESS-TRANSACTION" in names
    assert any(e["kind"] == "perform" and e["to"] == "PROCESS-TRANSACTION" for e in edges)


def test_normalize_relation_graph_drops_dangling_and_keeps_sequence():
    graph = normalize_relation_graph({
        "generated_by": "agent",
        "nodes": [
            {"id": "pgm:A", "label": "A", "kind": "program", "rank": 0, "seq": 0, "path": "a.cbl", "evidence": ["a.cbl:1"]},
            {"id": "para:A:MAIN", "label": "MAIN", "kind": "paragraph", "rank": 0, "seq": 1, "path": "a.cbl"},
            {"id": "ghost", "label": "nope", "kind": "rule"},
        ],
        "edges": [
            {"source": "pgm:A", "target": "para:A:MAIN", "kind": "next", "evidence": ["a.cbl:12"]},
            {"source": "pgm:A", "target": "missing", "kind": "call"},
            {"source": "para:A:MAIN", "target": "para:A:MAIN", "kind": "loop"},
        ],
    })
    ids = {n["id"] for n in graph["nodes"]}
    assert graph["generated_by"] == "agent"
    assert "pgm:A" in ids and "para:A:MAIN" in ids
    kinds = {e["kind"] for e in graph["edges"]}
    assert "next" in kinds and "loop" in kinds
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])


def test_procedure_flowchart_is_one_pseudocode_sequence():
    text = (BANKING / "account_lookup.cbl").read_text()
    nodes, edges = procedure_flowchart(text, "ACCOUNT-LOOKUP")
    kinds = {n["kind"] for n in nodes}
    labels = [n["label"] for n in nodes]
    assert nodes[0]["kind"] == "start"
    assert nodes[-1]["kind"] == "end"
    assert "loop" in kinds and "decision" in kinds
    assert any("DISPLAY" in lab for lab in labels)
    assert any(e["kind"] == "loop" for e in edges)
    assert not any(".cbl" in lab or "src/" in lab for lab in labels)


def test_monolith_perform_is_inlined_not_file_sliced():
    text = (BANKING / "transaction_posting.cbl").read_text()
    nodes, edges = procedure_flowchart(text, "TRANSACTION-POSTING")
    labels = [n["label"] for n in nodes]
    assert any(lab.startswith("PERFORM PROCESS-TRANSACTION") for lab in labels)
    assert any("ADD TR-AMOUNT" in lab or lab.startswith("ADD ") for lab in labels)
    assert any("DEPOSIT" in lab for lab in labels)
    starts = [n for n in nodes if n["kind"] == "start"]
    assert len(starts) == 1


def test_normalize_keeps_flowchart_kinds():
    graph = normalize_relation_graph({
        "generated_by": "agent",
        "nodes": [
            {"id": "s0", "label": "start", "kind": "start", "seq": 0, "evidence": ["a.cbl:1"]},
            {"id": "s1", "label": "amount > 10000?", "kind": "decision", "seq": 1},
        ],
        "edges": [{"source": "s0", "target": "s1", "kind": "next", "label": ""}],
    })
    kinds = {n["kind"] for n in graph["nodes"]}
    assert kinds == {"start", "decision"}
    assert graph["edges"][0]["kind"] == "next"
    assert is_flowchart_graph(graph)


def test_estate_logic_flowchart_is_one_origin_river():
    lookup = procedure_flowchart((BANKING / "account_lookup.cbl").read_text(), "ACCOUNT-LOOKUP")
    aml = procedure_flowchart((BANKING / "aml_flagging.cbl").read_text(), "AML-FLAGGING")
    graph = estate_logic_flowchart([
        {"program_id": "ACCOUNT-LOOKUP", "path": "src/account_lookup.cbl", "flow_nodes": lookup[0], "flow_edges": lookup[1]},
        {"program_id": "AML-FLAGGING", "path": "src/aml_flagging.cbl", "flow_nodes": aml[0], "flow_edges": aml[1]},
    ])
    kinds = {n["kind"] for n in graph["nodes"]}
    assert graph["generated_by"] == "procedure-logic"
    assert "origin" in {n["id"] for n in graph["nodes"]}
    assert "decision" in kinds and "loop" in kinds
    origin_outs = [e for e in graph["edges"] if e["source"] == "origin"]
    assert len(origin_outs) == 2
    assert not any(str(n["label"]).startswith("DISPLAY") for n in graph["nodes"])
    assert is_flowchart_graph(graph)


def test_br_call_is_deduped_across_files_in_a_module(tmp_path: Path):
    (tmp_path / "a.cob").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. A.\nPROCEDURE DIVISION.\nCALL 'OPS'.\n",
        encoding="utf-8",
    )
    (tmp_path / "b.cob").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. B.\nPROCEDURE DIVISION.\nCALL 'OPS'.\n",
        encoding="utf-8",
    )
    (tmp_path / "ops.cob").write_text(
        "IDENTIFICATION DIVISION.\nPROGRAM-ID. OPS.\nPROCEDURE DIVISION.\nX.\n",
        encoding="utf-8",
    )
    pack = build_exploration_pack("run-dedup", tmp_path)
    ids = [r["id"] for m in pack["modules"] for r in m["business_rules"]]
    assert ids.count("BR-CALL-OPS") == 1


def test_compress_flowchart_keeps_logic_gates():
    text = (BANKING / "account_lookup.cbl").read_text()
    nodes, edges = procedure_flowchart(text, "ACCOUNT-LOOKUP")
    compact, _cedges = compress_flowchart(nodes, edges)
    kinds = {n["kind"] for n in compact}
    assert "decision" in kinds and "loop" in kinds
    assert 4 <= len(compact) <= 12
    assert not any(str(n["label"]).startswith("DISPLAY") for n in compact)


def test_flowchart_to_mermaid_uses_diamonds_and_cylinders():
    md = flowchart_to_mermaid({
        "nodes": [
            {"id": "s", "label": "Start lookup", "kind": "start"},
            {"id": "dat", "label": "Accounts", "kind": "data"},
            {"id": "d", "label": "Match account", "kind": "decision"},
            {"id": "e", "label": "End", "kind": "end"},
        ],
        "edges": [
            {"source": "s", "target": "dat", "kind": "reads"},
            {"source": "dat", "target": "d", "kind": "next"},
            {"source": "d", "target": "e", "kind": "yes"},
            {"source": "d", "target": "e", "kind": "no"},
        ],
    })
    assert md.startswith("flowchart TD")
    assert 's(["Start lookup"])' in md
    assert 'dat[("Accounts")]' in md
    assert 'd{"Match account"}' in md
    assert "yes" in md and "no" in md


def test_as_is_markdown_keeps_flowchart_not_empty_call():
    from exploration_documentation import _as_is_diagrams_markdown
    md = _as_is_diagrams_markdown({
        "relation_graph": {
            "generated_by": "agent",
            "nodes": [
                {"id": "s", "label": "Start AML", "kind": "start", "evidence": ["aml.cbl:10"]},
                {"id": "d", "label": "Amount over threshold", "kind": "decision", "evidence": ["aml.cbl:17"]},
                {"id": "e", "label": "End AML", "kind": "end", "evidence": ["aml.cbl:31"]},
            ],
            "edges": [
                {"source": "s", "target": "d", "kind": "next"},
                {"source": "d", "target": "e", "kind": "yes"},
            ],
        },
        "call_graph_resolved": {"edges": []},
    })
    assert "flowchart TD" in md
    assert "Amount over threshold" in md
    assert "No resolved CALL edges" in md
    assert "aml.cbl:17" in md
