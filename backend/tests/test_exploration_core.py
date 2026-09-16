from pathlib import Path

from exploration_core import build_exploration_pack, parse_structural


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
