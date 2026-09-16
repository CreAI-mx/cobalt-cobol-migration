// Typed API client — mirrors backend/models.py 1:1 (field names never renamed).

export interface TreeNode {
  name: string;
  type: 'dir' | 'file';
  is_cobol: boolean;
  children?: TreeNode[] | null;
}

export interface IntakeResponse {
  run_id: string;
  total_files: number;
  cobol_files: number;
  tree: TreeNode;
}

export type PhaseStatus = 'OK' | 'BLOCKED' | 'SKIPPED' | 'RUNNING';
export type RunStatus = 'RUNNING' | 'PASSED' | 'FAILED' | 'ABORTED';
export type GateStatus = 'none' | 'pending' | 'approved' | 'rejected';

/** `type` is the SSE discriminator on the target contract; the current backend
 * omits it on phase events, so it stays optional and normalization (in
 * useMigrationEvents) stamps 'phase' on receipt. */
export interface PhaseEvent {
  type?: 'phase';
  phase: string;
  skill: string;
  status: PhaseStatus;
  detail: string;
}

export interface FileEvent {
  type: 'file';
  run_id: string;
  phase: string;
  file_path: string;
  status: string;
  detail: string;
}

export type MigrationEvent = (PhaseEvent & { type: 'phase' }) | FileEvent;

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  phases: PhaseEvent[];
  /** Being added by a concurrent backend change — absent on older builds. */
  gate_status?: GateStatus;
}

export interface CostLogEntry {
  phase: string;
  agent_id: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms?: number | null;
}

async function parseOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
      else if (Array.isArray(body?.detail)) {
        detail = body.detail
          .map((d: { msg?: string } | string) => (typeof d === 'string' ? d : d.msg ?? JSON.stringify(d)))
          .join('; ')
      }
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface IntakeSource {
  file?: File
  repoUrl?: string
}

/** Zip of runs/{id}/csharp/ — GET /migration/{run_id}/artifact.zip */
export function artifactZipUrl(runId: string): string {
  return `/migration/${encodeURIComponent(runId)}/artifact.zip`
}

/** Pushes the generated C# to a new public GitHub repo under the machine's
 * already-registered account — POST /migration/{run_id}/github-push. No token
 * is collected client-side; the backend reuses the stored git credential. */
export async function pushToGithub(runId: string): Promise<{ repo_url: string }> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/github-push`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  return parseOrThrow<{ repo_url: string }>(res)
}

export async function intake(source: IntakeSource): Promise<IntakeResponse> {
  const fd = new FormData()
  // URL wins: never attach a leftover zip when a GitHub URL is present.
  if (source.repoUrl) fd.append('repo_url', source.repoUrl)
  else if (source.file) fd.append('file', source.file)
  const res = await fetch('/migration/intake', { method: 'POST', body: fd })
  return parseOrThrow<IntakeResponse>(res)
}

export async function postGate(
  runId: string,
  decision: 'approved' | 'rejected' | 'pending',
  comment = '',
): Promise<RunStatusResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/gate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, comment }),
  })
  return parseOrThrow<RunStatusResponse>(res)
}

export interface GateHistoryEntry {
  decision: 'approved' | 'rejected' | 'pending';
  comment: string;
  created_at: string;
}

export async function getGateHistory(runId: string): Promise<GateHistoryEntry[]> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/gate/history`);
  return parseOrThrow<GateHistoryEntry[]>(res);
}

export type ArchShape = 'clean' | 'per-program' | 'one-to-one'
export type ArchAction = 'none' | 'recreated' | 'accepted'

export interface ArchitectureDecision {
  run_id: string
  revision: number
  shape: ArchShape
  directive: string
  action: ArchAction
  created_at?: string | null
}

export async function getArchitecture(runId: string): Promise<ArchitectureDecision> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/architecture`)
  return parseOrThrow<ArchitectureDecision>(res)
}

export async function postArchitecture(
  runId: string,
  body: { shape: ArchShape; directive: string; action: 'recreated' | 'accepted' },
): Promise<ArchitectureDecision> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/architecture`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseOrThrow<ArchitectureDecision>(res)
}

export interface RunHistoryEntry {
  run_id: string
  started_at: string
  finished_at: string | null
  status: RunStatus
  source_repo: string
  target_lang: string
  total_files: number
  cobol_files: number
  /** True while the pipeline asyncio task is still running. */
  live?: boolean
}

export async function listRuns(limit = 50): Promise<RunHistoryEntry[]> {
  const res = await fetch(`/migration/runs?limit=${limit}`);
  return parseOrThrow<RunHistoryEntry[]>(res);
}

export interface RunDetail {
  run_id: string
  status: RunStatus
  source_repo: string
  started_at: string
  finished_at: string | null
  live: boolean
  events: MigrationEvent[]
}

/** Full picture of ANY run (live or long-dead), sourced from persisted DB
 * tables — works after a server restart, unlike the SSE stream. */
export async function getRunDetail(runId: string): Promise<RunDetail> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/detail`);
  return parseOrThrow<RunDetail>(res);
}


export interface ParityTerminalPane {
  title: string
  command: string
  stdout: string
  exit_code: number
  ok: boolean
}

export type ParityDemoSide = 'both' | 'cobol' | 'csharp'

export interface ParityFieldDiff {
  field: string
  label: string
  equal: boolean
  cobol: string
  csharp: string
  fix_hint?: string | null
  display_equal?: boolean
  numeric_equal?: boolean
}

export type ParityComparisonMode = 'structured' | 'lines'

export interface ParityComparison {
  output_equal: boolean
  display_equal: boolean
  /** structured = parsed fields; lines = normalized stdout diff */
  mode?: ParityComparisonMode
  diffs: ParityFieldDiff[]
}

export interface ParityDemoResponse {
  run_id: string
  side?: ParityDemoSide
  parity_engine?: string
  fixture: string | null
  cobol: ParityTerminalPane
  csharp: ParityTerminalPane
  verdict: 'match' | 'partial' | 'blocked' | 'review'
  summary: string
  comparison?: ParityComparison | null
}


export interface AgentStackConfig {
  run_id: string
  circumstance: string
  tools: Record<string, boolean>
  updated_at?: string | null
}

export async function getAgentStack(runId: string): Promise<AgentStackConfig> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/agent-stack`)
  return parseOrThrow<AgentStackConfig>(res)
}

export async function postAgentRerun(runId: string): Promise<RunStatusResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/agent-rerun`, { method: 'POST' })
  return parseOrThrow<RunStatusResponse>(res)
}

export async function putAgentStack(runId: string, body: AgentStackConfig): Promise<AgentStackConfig> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/agent-stack`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseOrThrow<AgentStackConfig>(res)
}

export async function postParityDemo(
  runId: string,
  side: ParityDemoSide = 'both',
): Promise<ParityDemoResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/parity-demo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ side }),
  })
  return parseOrThrow<ParityDemoResponse>(res)
}

export async function startPipeline(runId: string): Promise<RunStatusResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/start`, { method: 'POST' });
  return parseOrThrow<RunStatusResponse>(res);
}

export async function getTree(runId: string): Promise<TreeNode> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/tree`);
  return parseOrThrow<TreeNode>(res);
}

export type FileKind = 'cobol_source' | 'copybook' | 'doc' | 'other'

export interface SourceFileView {
  path: string
  kind: FileKind
  content: string
  loc: number
  truncated: boolean
  binary: boolean
  program_id?: string | null
}

export async function getSourceFile(runId: string, path: string): Promise<SourceFileView> {
  const q = new URLSearchParams({ path })
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/file?${q}`)
  return parseOrThrow<SourceFileView>(res)
}

/** Reads the REAL generated C# output (Phase 4/5 wrote it to disk already) —
 * distinct from getSourceFile, which only ever reads the original COBOL. */
export async function getGeneratedFile(runId: string, path: string): Promise<SourceFileView> {
  const q = new URLSearchParams({ path })
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/generated-file?${q}`)
  return parseOrThrow<SourceFileView>(res)
}

export interface BusinessLogicExtract {
  extract_id: string
  file_id: string
  path: string
  user_stories: unknown[]
  business_rules: unknown[]
  suggested_component_name?: string | null
  created_at: string
}

export async function getExtracts(runId: string): Promise<BusinessLogicExtract[]> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/extracts`)
  return parseOrThrow<BusinessLogicExtract[]>(res)
}

export async function getStatus(runId: string): Promise<RunStatusResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/status`);
  return parseOrThrow<RunStatusResponse>(res);
}

export async function getCost(runId: string): Promise<CostLogEntry[]> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/cost`);
  return parseOrThrow<CostLogEntry[]>(res);
}

export function openEventStream(runId: string): EventSource {
  return new EventSource(`/migration/${encodeURIComponent(runId)}/events`);
}

export type WorkItemStatus =
  | 'pending'
  | 'analyzing'
  | 'generating'
  | 'building'
  | 'testing'
  | 'completed'
  | 'failed'

export type WorkItemKind = 'conversion' | 'persistence' | 'cli' | 'tests' | 'documentation'

export interface WorkItem {
  work_item_id: string
  slug: string
  title: string
  kind: WorkItemKind
  status: WorkItemStatus
  source_paths: string[]
  expected_paths: string[]
  depends_on: string[]
  wave: number
  retry_count: number
  workspace_rel: string
  agent_id: string | null
  error: string | null
  artifact_count: number
}

export interface UiBlock {
  type: 'work_item_list' | 'active_agents' | 'build_gate' | 'test_gate' | 'download' | 'decision_required'
  [key: string]: unknown
}

export interface MigrationPlan {
  plan_id: string
  run_id: string
  summary: string
  solution_name: string
  stage: string
  work_items: WorkItem[]
  ui_blocks: UiBlock[]
  live?: boolean
  progress: {
    work_items_done: number
    work_items_total: number
    work_items_failed: number
    artifacts_integrated: number
    artifacts_expected: number
    percent: number
  }
}

export async function getPlan(runId: string): Promise<MigrationPlan> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/plan`)
  return parseOrThrow<MigrationPlan>(res)
}

export async function postPlan(runId: string): Promise<MigrationPlan> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/plan`, { method: 'POST' })
  return parseOrThrow<MigrationPlan>(res)
}

export interface FlowNode {
  id: string
  label: string
  kind: 'start' | 'process' | 'decision' | 'loop' | 'call' | 'end' | 'merge'
  seq: number
  line?: number
}

export interface FlowEdge {
  source: string
  target: string
  kind: string
  label?: string
}

export interface ExplorationProgram {
  path: string
  program_id?: string | null
  module_id?: string | null
  complexity_tier?: string
  paragraphs?: string[]
  procedure_edges?: { from: string; to: string; kind: string }[]
  flow_nodes?: FlowNode[]
  flow_edges?: FlowEdge[]
  call_targets?: string[]
  loc?: number
}

export interface RelationGraphNode {
  id: string
  label: string
  kind: 'program' | 'paragraph' | 'data' | 'external' | 'start' | 'process' | 'decision' | 'loop' | 'call' | 'end' | 'merge'
  rank?: number
  seq?: number
  path?: string | null
  evidence?: string[]
}

export interface RelationGraph {
  schema: number
  generated_by?: string
  nodes: RelationGraphNode[]
  edges: { source: string; target: string; kind: string; label?: string; evidence?: string[] }[]
}

export interface ExplorationModule {
  module_id: string
  title: string
  source_program_ids: string[]
  member_paths: string[]
  entrypoint_program_id?: string | null
  entrypoint_path?: string | null
  conversion_order_hint: number
  suggested_target_projects: string[]
  business_rules: { id: string; text: string; anchors: string[]; source?: string }[]
  risks: string[]
  human_notes: string
}

export interface ExplorationPack {
  exploration_pack_schema: number
  run_id: string
  locked_at: string | null
  inventory_summary: { files: number; programs: number; copybooks: number }
  modules: ExplorationModule[]
  programs?: ExplorationProgram[]
  call_graph_resolved: { edges: { from_path: string; to_path: string; edge_type: string; target_program_id?: string }[] }
  relation_graph?: RelationGraph
  open_items: { id: string; text: string; status: string }[]
  planner_seed: { work_item_hints: unknown[]; directive_fragments: string[] }
  documentation?: {
    scope: string
    root: string
    documents: string[]
    agent_status: string
    corpus?: { files_copied: number; archive_members_expanded: number }
    cost_usd?: number
    input_tokens?: number
    output_tokens?: number
    graph: {
      schema: number
      generated_by?: string
      nodes: { id: string; label: string; kind: 'program' | 'rule' | 'risk' | 'question' | 'document'; x: number; y: number; evidence?: string[] }[]
      edges: { source: string; target: string; kind: string; evidence?: string[] }[]
    }
  }
}

export function explorationDocsZipUrl(runId: string): string {
  return `/migration/${encodeURIComponent(runId)}/exploration/docs.zip`
}

export function explorationDocumentUrl(runId: string, path: string): string {
  return `/migration/${encodeURIComponent(runId)}/exploration/docs/${path.split('/').map(encodeURIComponent).join('/')}`
}

export interface ExplorationSessionResponse {
  run_id: string
  status: string
  started_at: string | null
  finished_at: string | null
  draft_pack: ExplorationPack | null
  locked_pack: ExplorationPack | null
  locked_at: string | null
  live: boolean
}

export interface ExplorationDocsManifest {
  run_id: string
  documents: string[]
  agent_status: string
  corpus?: { files_copied: number; archive_members_expanded: number }
}

export async function getExplorationDocsManifest(runId: string): Promise<ExplorationDocsManifest | null> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/exploration/docs/manifest`)
  if (res.status === 404) return null
  return parseOrThrow<ExplorationDocsManifest>(res)
}

export async function getExplorationStatus(runId: string): Promise<ExplorationSessionResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/exploration/status`)
  return parseOrThrow<ExplorationSessionResponse>(res)
}

export async function postExplorationStart(runId: string): Promise<ExplorationSessionResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/exploration/start`, { method: 'POST' })
  return parseOrThrow<ExplorationSessionResponse>(res)
}

export async function postExplorationLock(runId: string): Promise<ExplorationSessionResponse> {
  const res = await fetch(`/migration/${encodeURIComponent(runId)}/exploration/lock`, { method: 'POST' })
  return parseOrThrow<ExplorationSessionResponse>(res)
}

export async function postModuleNotes(
  runId: string,
  moduleId: string,
  text: string,
): Promise<{ module_id: string; human_notes: string }> {
  const res = await fetch(
    `/migration/${encodeURIComponent(runId)}/exploration/modules/${encodeURIComponent(moduleId)}/notes`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    },
  )
  return parseOrThrow(res)
}
