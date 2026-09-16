"""Agent stack config persistence."""
from pathlib import Path

import agent_stack


def test_save_and_load_circumstance(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_stack, "RUNS_DIR", tmp_path)
    rid = "TESTRUN01"
    agent_stack.save_config(rid, circumstance="parity on lookup", tools={"parity-oracle": True})
    cfg = agent_stack.load_config(rid)
    assert cfg["circumstance"] == "parity on lookup"
    assert cfg["tools"]["parity-oracle"] is True
    assert Path(tmp_path / rid / "agent_stack.json").is_file()


def test_circumstance_for_run_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_stack, "RUNS_DIR", tmp_path)
    assert agent_stack.circumstance_for_run("NOFILE") == ""
