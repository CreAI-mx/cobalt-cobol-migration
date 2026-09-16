// RunContext-level SSE subscription (design §Navigation): lives at App level so
// navigating between wizard steps only stops RENDERING the feed, never
// unsubscribes. The full event log is buffered here and replayed to any step
// that mounts later.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { getArchitecture, getCost, getGateHistory, getPlan, getRunDetail, getStatus, getTree, intake as postIntake, openEventStream, postAgentRerun, postArchitecture, postGate, postPlan, startPipeline } from '../lib/api';
import type {
  ArchitectureDecision,
  CostLogEntry,
  GateStatus,
  IntakeResponse,
  IntakeSource,
  MigrationEvent,
  MigrationPlan,
  PhaseEvent,
  RunStatus,
  TreeNode,
} from '../lib/api';
import type { ArchShape } from '../lib/targetArchitecture';
import { clearWizardSession, readWizardSession } from '../lib/wizardSession';

/** HITL decision on the architecture proposal (Step 4). Persisted via
 * POST /migration/{run_id}/gate (`changes_requested` maps to `rejected`). */
export type ProposalDecision = 'pending' | 'approved' | 'changes_requested'

export interface ProposalReview {
  decision: ProposalDecision
  comment: string
}

export interface RunState {
  intake: IntakeResponse | null;
  runId: string | null;
  /** Full ordered event log (phase + file events), deduped across SSE reconnects. */
  events: MigrationEvent[];
  /** Latest event per phase id ("Phase 0" … "Phase 8"). */
  phaseMap: Map<string, PhaseEvent>;
  /** Latest status per file_path, from FileEvents. */
  fileStatus: Map<string, string>;
  runStatus: RunStatus | null;
  gateStatus: GateStatus;
  cost: CostLogEntry[];
  /** True while the pipeline is streaming — drives the LIVE chip on Step 5. */
  live: boolean;
  error: string | null;
  proposal: ProposalReview;
  decideProposal: (decision: ProposalDecision, comment: string) => Promise<void>;
  architecture: ArchitectureDecision;
  previewArchitecture: (partial: { shape?: ArchShape; directive?: string }) => void;
  submitArchitecture: (body: {
    shape: ArchShape
    directive: string
    action: 'recreated' | 'accepted'
  }) => Promise<void>;
  doIntake: (source: IntakeSource) => Promise<IntakeResponse>;
  /** Pass the run id explicitly when calling right after doIntake resolves —
   * the closure's runId state may not have propagated yet. */
  doStart: (runId?: string) => Promise<void>;
  doPlan: (runId?: string) => Promise<void>;
  plan: MigrationPlan | null;
  /** Re-run the pipeline for the SAME run_id after a FAILED/ABORTED status —
   * resets client-side stream state and calls doStart again. */
  retry: () => Promise<void>;
  /** Re-run foreman with agent-stack circumstance (POST /agent-rerun). */
  agentRerun: () => Promise<void>;
  /** Load a PAST run (from Execution History) into this same live-view state,
   * frozen (live=false) — same Step 5 experience, not a separate summary. */
  loadHistoricalRun: (runId: string, totalFiles: number, cobolFiles: number) => Promise<void>;
  /** Leave the current run — Home is a blank landing, not the last execution. */
  goHome: () => void;
  /** False until boot restore from localStorage finishes (or there was nothing to restore). */
  hydrated: boolean;
  /** Persisted run clock from GET /detail — drives the Step 5 timer. */
  startedAt: string | null
  finishedAt: string | null;
}

const RunContext = createContext<RunState | null>(null);
export const RunProvider = RunContext.Provider;

export function useRun(): RunState {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error('useRun must be used inside RunProvider');
  return ctx;
}

/** Backward compat: events without a `type` discriminator are phase events. */
function normalizeEvent(raw: Record<string, unknown>): MigrationEvent {
  if (raw.type === 'file') return raw as unknown as MigrationEvent;
  return { ...raw, type: 'phase' } as MigrationEvent;
}

/** Dedup key — the SSE generator replays from index 0 on reconnect. */
function eventKey(e: MigrationEvent): string {
  return e.type === 'file'
    ? `f|${e.phase}|${e.file_path}|${e.status}|${e.detail}`
    : `p|${e.phase}|${e.status}|${e.detail}`;
}

function gateToProposal(
  decision: string | undefined,
  comment: string,
): ProposalReview {
  if (decision === 'approved') return { decision: 'approved', comment }
  if (decision === 'rejected') return { decision: 'changes_requested', comment }
  return { decision: 'pending', comment }
}

function countTree(node: TreeNode): { total: number; cobol: number } {
  let total = 0
  let cobol = 0
  const walk = (n: TreeNode) => {
    if (n.type === 'file') {
      total += 1
      if (n.is_cobol) cobol += 1
    }
    for (const c of n.children ?? []) walk(c)
  }
  walk(node)
  return { total, cobol }
}

export function useMigrationEvents(): RunState {
  const [intakeRes, setIntakeRes] = useState<IntakeResponse | null>(null);
  const [events, setEvents] = useState<MigrationEvent[]>([]);
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null);
  const [gateStatus, setGateStatus] = useState<GateStatus>('none');
  const [cost, setCost] = useState<CostLogEntry[]>([]);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ProposalReview>({ decision: 'pending', comment: '' });
  const [architecture, setArchitecture] = useState<ArchitectureDecision>({
    run_id: '',
    revision: 0,
    shape: 'clean',
    directive: '',
    action: 'none',
  });
  const esRef = useRef<EventSource | null>(null);
  const closeStream = useCallback(() => {
    const s = esRef.current;
    if (s) s.close();
    esRef.current = null;
  }, []);
  const seenRef = useRef<Set<string>>(new Set());
  const startedRef = useRef(false);
  const intakeRef = useRef<IntakeResponse | null>(null);
  const sseErrorsRef = useRef(0);
  const [hydrated, setHydrated] = useState(false)
  const [startedAt, setStartedAt] = useState<string | null>(null)
  const [finishedAt, setFinishedAt] = useState<string | null>(null)
  const [plan, setPlan] = useState<MigrationPlan | null>(null)

  const previewArchitecture = useCallback((partial: { shape?: ArchShape; directive?: string }) => {
    setArchitecture((prev) => ({ ...prev, ...partial }));
  }, []);

  const submitArchitecture = useCallback(async (body: {
    shape: ArchShape
    directive: string
    action: 'recreated' | 'accepted'
  }) => {
    setArchitecture((prev) => ({ ...prev, shape: body.shape, directive: body.directive, action: body.action }));
    const id = intakeRef.current?.run_id;
    if (!id) return;
    try {
      const res = await postArchitecture(id, body);
      setArchitecture(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const decideProposal = useCallback(async (decision: ProposalDecision, comment: string) => {
    setProposal({ decision, comment });
    setGateStatus(decision === 'pending' ? 'none' : (decision as GateStatus));
    // Persist "pending" too (Revisit decision) — a local-only reset gets
    // clobbered back to the DB's last 'rejected'/'approved' row on the next
    // status poll otherwise (real bug: Revisit appeared to do nothing).
    const id = intakeRef.current?.run_id;
    if (!id) return;
    try {
      const apiDecision = decision === 'changes_requested' ? 'rejected' : decision
      const res = await postGate(id, apiDecision, comment)
      setGateStatus(res.gate_status ?? 'none');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const runId = intakeRes?.run_id ?? null;

  const doIntake = useCallback(async (source: IntakeSource) => {
    setError(null);
    const res = await postIntake(source);
    intakeRef.current = res;
    setIntakeRes(res);
    setArchitecture({
      run_id: res.run_id,
      revision: 0,
      shape: 'clean',
      directive: '',
      action: 'none',
    });
    void getArchitecture(res.run_id).then(setArchitecture).catch(() => { /* none yet */ });
    return res;
  }, []);

  const doPlan = useCallback(async (idArg?: string) => {
    const id = idArg ?? intakeRef.current?.run_id
    if (!id) return
    try {
      const next = await postPlan(id)
      setPlan(next)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, []);

  const subscribe = useCallback((id: string) => {
    if (esRef.current) return;
    const es = openEventStream(id);
    esRef.current = es;
    es.onmessage = (msg) => {
      sseErrorsRef.current = 0;
      try {
        const ev = normalizeEvent(JSON.parse(msg.data));
        if (ev.type === 'phase' && ev.phase === '__done__') {
          setLive(false);
          es.close();
          esRef.current = null;
          void getStatus(id).then((res) => {
            setRunStatus(res.status);
            setGateStatus(res.gate_status ?? 'none');
          }).catch(() => { /* status is best-effort at stream end */ });
          void getCost(id).then(setCost).catch(() => { /* cost optional */ });
          return;
        }
        const key = eventKey(ev);
        if (seenRef.current.has(key)) return;
        seenRef.current.add(key);
        setEvents((prev) => [...prev, ev]);
      } catch {
        /* malformed frame — skip, never crash the stream */
      }
    };
    // EventSource auto-reconnects when the server closes the stream; the dedup
    // set makes the replay harmless. Final close happens in doStart's finally.
    // Repeated failures without any message = the stream is genuinely broken:
    // surface it and stop the reconnect storm instead of a LIVE chip lying.
    es.onerror = () => {
      sseErrorsRef.current += 1;
      if (sseErrorsRef.current >= 5) {
        es.close();
        esRef.current = null;
        setError('Event stream lost after repeated reconnect failures — check the backend and reload.');
      }
    };
  }, []);

  const doStart = useCallback(async (idArg?: string) => {
    // intakeRef makes a bare doStart() safe even in the same tick as intake.
    const id = idArg ?? intakeRef.current?.run_id ?? runId;
    if (!id || startedRef.current) return;
    startedRef.current = true;
    setError(null);
    setLive(true);
    setFinishedAt(null)
    setStartedAt((prev) => prev ?? new Date().toISOString())
    subscribe(id);
    try {
      const res = await startPipeline(id);
      setRunStatus(res.status);
      setGateStatus(res.gate_status ?? 'none');
      // /start returns immediately; SSE stays open until __done__.
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRunStatus('FAILED');
      setLive(false);
      esRef.current?.close();
      esRef.current = null;
    }
  }, [runId, subscribe]);


  const agentRerun = useCallback(async () => {
    const id = intakeRef.current?.run_id ?? runId;
    if (!id) return;
    startedRef.current = false;
    seenRef.current = new Set();
    setEvents([]);
    setRunStatus(null);
    setError(null);
    setFinishedAt(null);
    closeStream();
    setLive(true);
    startedRef.current = true;
    subscribe(id);
    try {
      const res = await postAgentRerun(id);
      setRunStatus(res.status);
      setGateStatus(res.gate_status ?? 'none');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRunStatus('FAILED');
      setLive(false);
      closeStream();
    }
  }, [runId, subscribe, closeStream]);

  const retry = useCallback(async () => {
    const id = intakeRef.current?.run_id ?? runId;
    if (!id) return;
    // /start is idempotent-safe to call again once the prior run is no longer
    // live (backend resets _run_state and spawns a fresh _execute_run task) —
    // this just resets the CLIENT-side guards/log so a retry looks like a
    // clean new stream instead of replaying/duplicating the failed one.
    startedRef.current = false;
    seenRef.current = new Set();
    setEvents([]);
    setRunStatus(null);
    setError(null);
    setFinishedAt(null)
    esRef.current?.close();
    esRef.current = null;
    await doStart(id);
  }, [runId, doStart]);

  const hydrateRun = useCallback(async (
    id: string,
    totalFiles: number,
    cobolFiles: number,
    opts: { assumeApproved?: boolean; reconnectLive?: boolean } = {},
  ) => {
    esRef.current?.close();
    esRef.current = null;
    setError(null);
    setEvents([]);
    seenRef.current = new Set();
    const [tree, detail, arch, history, rows, manifesto] = await Promise.all([
      getTree(id),
      getRunDetail(id),
      getArchitecture(id).catch(() => null),
      getGateHistory(id).catch(() => []),
      getCost(id).catch(() => []),
      getPlan(id).catch(() => null),
    ]);
    const counted = countTree(tree);
    const res = {
      run_id: id,
      total_files: totalFiles || counted.total,
      cobol_files: cobolFiles || counted.cobol,
      tree,
    };
    intakeRef.current = res;
    setIntakeRes(res);
    const incoming = Array.isArray(detail.events) ? detail.events : [];
    setEvents(incoming);
    seenRef.current = new Set(incoming.map(eventKey));
    setRunStatus(detail.status);
    setStartedAt(detail.started_at ?? null)
    setFinishedAt(detail.finished_at ?? null)
    setCost(rows);
    setPlan(manifesto)
    if (arch) setArchitecture(arch);
    const last = history.at(-1);
    if (opts.assumeApproved && last?.decision !== 'rejected') {
      setProposal({ decision: 'approved', comment: last?.comment ?? '' });
      setGateStatus('approved');
    } else {
      setProposal(gateToProposal(last?.decision, last?.comment ?? ''));
      setGateStatus((last?.decision as GateStatus | undefined) ?? 'none');
    }
    const stillLive = Boolean(opts.reconnectLive && detail.live);
    setLive(stillLive);
    startedRef.current = true;
    if (stillLive) subscribe(id);
  }, [subscribe]);

  const loadHistoricalRun = useCallback(async (id: string, totalFiles: number, cobolFiles: number) => {
    // reconnectLive: true — hydrateRun only actually reconnects when the
    // backend confirms the run is still live (detail.live), so a genuinely
    // dead run stays frozen. Hardcoding false here meant opening a run that
    // was STILL RUNNING FOR REAL showed a stale FAILED badge instead of the
    // live stream (real bug, caught while QA-testing a retry mid-flight).
    await hydrateRun(id, totalFiles, cobolFiles, { assumeApproved: true, reconnectLive: true });
  }, [hydrateRun]);

  const goHome = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    startedRef.current = false;
    seenRef.current = new Set();
    sseErrorsRef.current = 0;
    intakeRef.current = null;
    setIntakeRes(null);
    setEvents([]);
    setRunStatus(null);
    setGateStatus('none');
    setCost([]);
    setLive(false);
    setError(null);
    setProposal({ decision: 'pending', comment: '' });
    setArchitecture({
      run_id: '',
      revision: 0,
      shape: 'clean',
      directive: '',
      action: 'none',
    });
    setStartedAt(null);
    setFinishedAt(null);
    setPlan(null);
    clearWizardSession();
  }, []);

  useEffect(() => {
    const saved = readWizardSession();
    if (!saved || saved.step === 0) {
      if (saved?.step === 0) clearWizardSession();
      setHydrated(true);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        await hydrateRun(saved.runId, 0, 0, {
          assumeApproved: saved.step === 4,
          reconnectLive: true,
        });
      } catch {
        if (!cancelled) clearWizardSession();
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrateRun]);

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    const tick = () => {
      void getPlan(runId)
        .then((next) => {
          if (!cancelled) setPlan(next)
        })
        .catch(() => { /* no plan yet */ })
    }
    tick()
    const handle = window.setInterval(tick, 2000)
    return () => {
      cancelled = true
      window.clearInterval(handle)
    }
  }, [runId])

  /** Poll persisted run state so ABORTED→RUNNING retries (or another tab's /start)
   * update the meter without a full page refresh. Reconnect SSE when backend live. */
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const [rows, arch, detail, manifesto] = await Promise.all([
          getCost(runId),
          getArchitecture(runId),
          getRunDetail(runId),
          getPlan(runId).catch(() => null),
        ]);
        if (cancelled) return;
        setCost(rows);
        if (manifesto) setPlan(manifesto);
        if (arch) {
          setArchitecture((prev) => {
            if (arch.revision > prev.revision) return arch;
            if (arch.revision >= prev.revision && arch.action !== prev.action) return arch;
            return prev;
          });
        }
        if (detail.status) setRunStatus(detail.status);
        if (detail.started_at) setStartedAt(detail.started_at);
        setFinishedAt(detail.finished_at ?? null);

        if (detail.live) {
          setLive(true);
          startedRef.current = true;
          if (!esRef.current) subscribe(runId);
        } else if (esRef.current) {
          closeStream();
          setLive(false);
        } else {
          setLive(false);
        }

        const incoming = Array.isArray(detail.events) ? detail.events : [];
        if (incoming.length === 0) return;
        setEvents((prev) => {
          const merged: MigrationEvent[] = [];
          const seen = new Set<string>();
          const ingest = (raw: MigrationEvent) => {
            const ev =
              raw.type === 'file' || raw.type === 'phase'
                ? raw
                : normalizeEvent(raw as unknown as Record<string, unknown>);
            const key = eventKey(ev);
            if (seen.has(key)) return;
            seen.add(key);
            merged.push(ev);
          };
          for (const e of incoming) ingest(e);
          for (const e of prev) ingest(e);
          seenRef.current = seen;
          if (
            merged.length === prev.length &&
            merged.every((e, i) => eventKey(e) === eventKey(prev[i]))
          ) {
            return prev;
          }
          return merged;
        });
      } catch {
        /* best-effort sync */
      }
    };
    void tick();
    const handle = window.setInterval(() => void tick(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [runId, subscribe, closeStream]);

  // Memoized: at demo scale the rebuild is negligible, but events are unbounded
  // on real estates (1000+ files) and every SSE message re-renders consumers.
  const { phaseMap, fileStatus } = useMemo(() => {
    const phases = new Map<string, PhaseEvent>();
    const files = new Map<string, string>();
    for (const e of events) {
      if (e.type === 'file') files.set(e.file_path, e.status);
      else phases.set(e.phase, e);
    }
    return { phaseMap: phases, fileStatus: files };
  }, [events]);

  return {
    intake: intakeRes,
    runId,
    events,
    phaseMap,
    fileStatus,
    runStatus,
    gateStatus,
    cost,
    live,
    error,
    proposal,
    decideProposal,
    architecture,
    previewArchitecture,
    submitArchitecture,
    doIntake,
    doStart,
    doPlan,
    plan,
    retry,
    agentRerun,
    loadHistoricalRun,
    goHome,
    hydrated,
    startedAt,
    finishedAt,
  };
}
