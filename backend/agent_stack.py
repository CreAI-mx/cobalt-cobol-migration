"""Per-run agent stack config — circumstance + tool toggles (agentic harness)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"

DEFAULT_TOOLS: dict[str, bool] = {
    "parity-oracle": True,
    "openapi-driver": True,
    "agent-review": False,
}


def _path(run_id: str) -> Path:
    return RUNS_DIR / run_id / "agent_stack.json"


def default_config(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "circumstance": "",
        "tools": dict(DEFAULT_TOOLS),
        "updated_at": None,
    }


def load_config(run_id: str) -> dict:
    p = _path(run_id)
    if not p.is_file():
        return default_config(run_id)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_config(run_id)
    base = default_config(run_id)
    base["circumstance"] = str(data.get("circumstance") or "")
    tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
    base["tools"] = {**DEFAULT_TOOLS, **{k: bool(v) for k, v in tools.items()}}
    base["updated_at"] = data.get("updated_at")
    return base


def save_config(run_id: str, *, circumstance: str | None = None, tools: dict[str, bool] | None = None) -> dict:
    cfg = load_config(run_id)
    if circumstance is not None:
        cfg["circumstance"] = circumstance
    if tools is not None:
        cfg["tools"] = {**DEFAULT_TOOLS, **tools}
    cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
    root = RUNS_DIR / run_id
    root.mkdir(parents=True, exist_ok=True)
    _path(run_id).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg


def circumstance_for_run(run_id: str) -> str:
    return (load_config(run_id).get("circumstance") or "").strip()
