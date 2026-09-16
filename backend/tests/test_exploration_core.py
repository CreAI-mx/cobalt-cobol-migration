from pathlib import Path

from exploration_core import build_exploration_pack, parse_structural, procedure_flow, normalize_relation_graph, procedure_flowchart


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
    text = Path("/home/frg/creai/cobol/migration-state/runs/01M2NH7YT3KB7X4NX9RNWRKG00/source/cobol-banking-systems/src/account_lookup.cbl").read_text()
    s = parse_structural(text)
    assert "FILE-CONTROL" not in s["paragraphs_json"]
    kinds = {e["kind"] for e in s["procedure_edges"]}
    assert "loop" in kinds


def test_perform_named_paragraph():
    text = Path("/home/frg/creai/cobol/migration-state/runs/01M2NH7YT3KB7X4NX9RNWRKG00/source/cobol-banking-systems/src/transaction_posting.cbl").read_text()
    names, edges = procedure_flow(text)
    assert "PROCESS-TRANSACTION" in names
    assert any(e["kind"] == "perform" and e["to"] == "PROCESS-TRANSACTION" for e in edges)


def test_normalize_relation_graph_drops_dangling_and_keeps_sequence():
    """Callers: pytest. Schema: relation_graph nodes/edges.
    User: un diagrama de relacion secuencia uno solo, construido agenticamente."""
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
    text = Path("/home/frg/creai/cobol/migration-state/runs/01M2NH7YT3KB7X4NX9RNWRKG00/source/cobol-banking-systems/src/account_lookup.cbl").read_text()
    nodes, edges = procedure_flowchart(text, "ACCOUNT-LOOKUP")
    kinds = {n["kind"] for n in nodes}
    labels = [n["label"] for n in nodes]
    assert nodes[0]["kind"] == "start"
    assert nodes[-1]["kind"] == "end"
    assert "loop" in kinds and "decision" in kinds
    assert any("DISPLAY" in lab for lab in labels)
    assert any(e["kind"] == "loop" for e in edges)
def test_normalize_keeps_flowchart_kinds():
    graph = normalize_relation_graph({
        "generated_by": "agent",
        "nodes": [
            {"id": "s0", "label": "start", "kind": "start", "seq": 0, "evidence": ["a.cbl:1"]},
            {"id": "s1", "label": "amount > 10000?", "kind": "decision", "seq": 1},
        ],
        "edges": [{"source": "s0", "target": "s1", "kind": "next"}],
    })
    kinds = {n["kind"] for n in graph["nodes"]}
    assert kinds == {"start", "decision"}
    assert graph["edges"][0]["kind"] == "next"
