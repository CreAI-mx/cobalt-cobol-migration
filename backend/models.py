"""Pydantic models mirroring migration-state/schema.sql 1:1.
This module IS the OpenAPI schema an agent reads at /openapi.json — keep field
names identical to the SQL columns, no renaming for prettiness."""
from typing import Optional, Literal
from pydantic import BaseModel

RunStatus = Literal["RUNNING", "PASSED", "FAILED", "ABORTED"]
FileKind = Literal["cobol_source", "copybook", "doc", "other"]
ComplexityTier = Literal["LOW", "MEDIUM", "HIGH"]
DivergenceClass = Literal["REAL_BUG", "INTENTIONAL_CHANGE", "REPRESENTATION_DIFFERENCE"]


class MigrationRun(BaseModel):
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    status: RunStatus
    target_lang: str = "csharp"
    source_repo: str
    notes: Optional[str] = None


class CobolFile(BaseModel):
    file_id: str
    run_id: str
    path: str
    program_id: Optional[str] = None
    loc: Optional[int] = None
    sha256: str
    # Scope change: table now inventories ALL project files, discriminated by kind
    # (column added via idempotent ALTER TABLE in db.init_db — table not renamed).
    file_kind: FileKind = "cobol_source"


class TreeNode(BaseModel):
    """Nested tree shape returned by GET /migration/{run_id}/tree — same shape a
    human UI renders and an agent parses."""
    name: str
    type: Literal["dir", "file"]
    is_cobol: bool = False
    children: Optional[list["TreeNode"]] = None


TreeNode.model_rebuild()


class IntakeResponse(BaseModel):
    run_id: str
    total_files: int
    cobol_files: int
    tree: TreeNode


class PhaseEvent(BaseModel):
    type: Literal["phase"] = "phase"
    phase: str
    skill: str
    status: Literal["OK", "BLOCKED", "SKIPPED", "RUNNING"]
    detail: str


class FileEvent(BaseModel):
    """Granular per-file progress event multiplexed with PhaseEvent on the same
    SSE stream — the `type` field is the discriminator."""
    type: Literal["file"] = "file"
    run_id: str
    phase: str
    file_path: str
    # SKIPPED: file not processed (e.g. Phase 2 budget cap) — distinct from FAILED.
    status: Literal["OK", "RUNNING", "FAILED", "SKIPPED"]
    detail: str


class RunStatusResponse(BaseModel):
    run_id: str
    status: RunStatus
    phases: list[PhaseEvent]
    gate_status: Literal["none", "pending", "approved", "rejected"] = "none"


class BusinessLogicExtract(BaseModel):
    """Row of business_logic_extracts joined with the file path, JSON columns
    parsed. suggested_component_name lives in a column added by db migration."""
    extract_id: str
    file_id: str
    path: str
    user_stories: list
    business_rules: list
    suggested_component_name: Optional[str] = None
    created_at: str


ArchShape = Literal["clean", "per-program", "one-to-one"]
ArchAction = Literal["none", "recreated", "accepted"]


class ArchitectureDecision(BaseModel):
    """HITL Step 3 — human co-authors the C# estate. Phase 4 waits on accepted.
    Importers: routers/pipeline.py POST/GET /architecture. Schema: architecture_decisions.
    User: componente human in the loop que participe en la creacion y proponga re arquitectura."""
    run_id: str
    revision: int = 0
    shape: ArchShape = "clean"
    directive: str = ""
    action: ArchAction = "none"
    created_at: Optional[str] = None


class SourceFileView(BaseModel):
    """GET /migration/{run_id}/file — origin preview. Real bytes from intake source/.
    Importers: frontend FilePeek. User: modal al click, origen abre el archivo."""
    path: str
    kind: FileKind = "other"
    content: str = ""
    loc: int = 0
    truncated: bool = False
    binary: bool = False
    program_id: Optional[str] = None


class CostLogEntry(BaseModel):
    phase: str
    agent_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: Optional[int] = None


class AgentStackConfig(BaseModel):
    """Editable agent harness brief + tool slots for a run (OpenAPI / agents)."""
    run_id: str
    circumstance: str = ""
    tools: dict[str, bool] = {}
    updated_at: Optional[str] = None
