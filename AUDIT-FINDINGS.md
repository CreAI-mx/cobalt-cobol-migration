# Cobalt — Audit Findings (2026-09-16)

Five parallel Codex audits (orchestrator/repair-loop, LLM generation, frontend,
security/deploy, production-ops), plus a test-coverage audit. All findings
below are verified against real file:line references (grep-confirmed), not
speculation. Jira-style: severity, one-line scenario, file:line, status.

Frontend audit AND the LLM-generation/COBOL-correctness audit both went idle
without returning a written report — rerun both before treating those two
areas as clean. Everything below is from the 4 audits that did report
(security/deploy, orchestrator, test-coverage, production-ops).

---

## P0 — Block before any real client / public deployment

### COBALT-1 — No authentication on any endpoint
Every endpoint (`intake`, `pipeline` routers) is open to anyone who can reach
the port. No auth middleware/dependency anywhere in `main.py`.
**Files:** `backend/main.py` (router mounts, no auth dependency)
**Fix:** add a shared-secret header or real auth dependency in front of both routers.
**Status:** OPEN

### COBALT-2 — github-push accepts an unvalidated repo_url and uses the real stored credential
`repo_url` from an unauthenticated POST body is passed straight to
`_git_push_with_stored_credential` with no scheme/host check (unlike intake's
`github_clone_url`, which does check). Anyone who can POST can force-push a
client's migrated code to an attacker-controlled repo using this machine's
real GitHub credential.
**Files:** `backend/routers/pipeline.py:606-624` (`github_push`), contrast with `backend/routers/intake.py:62-87` (`github_clone_url`, the correct pattern)
**Fix:** apply the same host/scheme allowlist `github_clone_url` already uses to `github_push`'s `repo_url` before use.
**Status:** OPEN

### COBALT-3 — Zip-bomb bypass in intake extraction
`MAX_UNCOMPRESSED_BYTES` guard sums attacker-controlled `member.file_size`
metadata from the zip's central directory *before* extracting — never
validates actual decompressed bytes. A crafted zip with tiny declared sizes
but highly-compressed payloads bypasses the guard entirely (classic zip-bomb DoS).
**Files:** `backend/routers/intake.py:119-153` (`_extract_zip`)
**Fix:** track cumulative bytes actually written during extraction (e.g. via `ZipFile.open()` + streamed read with a running counter), abort mid-extraction if the real total exceeds the cap.
**Status:** OPEN

### COBALT-4 — No cost cap enforcement despite a governance skill existing
`migration-cost-governance` skill is pure documentation — zero code imports
or invokes it. `cost_logs` is write-only (inserted after every headless call,
only ever read back for display). Nothing sums spend per run/tenant and
compares to a limit. Only ceiling is `MAX_RETRY × N_work_items` attempt count,
not a dollar figure.
**Files:** `backend/orchestrator.py:322-330` (`_log_cost`, write-only), `.claude/skills/migration-cost-governance/SKILL.md` (never invoked)
**Fix:** sum `cost_logs` per run_id at the top of `execute_migration`'s repair loop; abort with a clear BLOCKED status if a configurable ceiling (e.g. `COBALT_MAX_COST_USD`) is exceeded.
**Status:** OPEN

### COBALT-5 — Orphaned headless subprocesses on parent death
`claude -p` children are spawned with no process-group isolation and no
SIGTERM/SIGINT handler anywhere in the app. The only place a child is
`.kill()`'d is the `asyncio.TimeoutError` branch in the *same* coroutine. If
the uvicorn parent dies (crash, `kill -9`, the exact two-session collision
seen this session), every in-flight `claude -p` child is orphaned to init and
keeps running/spending tokens with nothing tracking or killing it.
**Files:** `backend/llm.py` (4 near-identical `asyncio.create_subprocess_exec` call sites, ~lines 147, 294, 464, 562)
**Fix:** spawn with `start_new_session=True` and register an app-level SIGTERM handler that kills the whole process group on shutdown.
**Status:** OPEN

### COBALT-6 — No global ceiling on concurrent runs
`COBALT_MAX_AGENTS` bounds parallelism *within* one run. Nothing limits how
many *different* run_ids can be started concurrently — N callers hitting N
distinct run_ids each spawn up to `MAX_AGENTS` headless processes with zero
global throttle.
**Files:** `backend/orchestrator.py:533` (the one `asyncio.gather` site with a bound), `backend/routers/pipeline.py:242-259` (`/start`, only guards the *same* run_id via an in-memory dict)
**Fix:** add a process-wide `asyncio.Semaphore` (env-configurable) shared across all `execute_migration` calls, acquired before spawning any headless subprocess.
**Status:** OPEN

---

## P1 — Real bugs, fix before wider use

### COBALT-7 — Cost of crashed/timed-out LLM calls is silently dropped
`HeadlessInvocationError` carries real `cost_usd`/token counts for tokens
already spent, but the `except` branches that catch it (in `_run_worker` and
the repair loop) never call `_log_cost` — that spend vanishes from `cost_logs`
entirely, undermining even the audit trail that exists today.
**Files:** `backend/orchestrator.py:454-474` (`_run_worker`), `backend/orchestrator.py:663-676` (repair loop's `except llm.HeadlessInvocationError`)
**Fix:** call `_log_cost` with `exc.cost_usd`/`exc.input_tokens`/`exc.output_tokens` in both except branches before continuing.
**Status:** OPEN

### COBALT-8 — Zip extraction doesn't reject symlink members
`_extract_zip` checks each member's *path* stays under the extraction root,
but never checks whether a member is a symlink whose *target* points outside
(e.g. `link -> /etc/passwd`). A later `GET /migration/{run_id}/file?path=link`
would resolve through the symlink and read arbitrary host files.
**Files:** `backend/routers/intake.py:140-153` (`_extract_zip`)
**Fix:** before/during extraction, reject any zip member with `S_IFLNK` set in its external attributes.
**Status:** OPEN

### COBALT-9 — Empty/junk zip commits a permanent stuck RUNNING row
`_inventory` inserts a `migration_runs` row with `status='RUNNING'` and
commits it *before* raising `HTTPException(422, "Source contains no files.")`
for an empty/all-non-COBOL zip. The row never reaches a terminal state except
via a full server restart (`_abort_orphaned_runs`).
**Files:** `backend/routers/intake.py` (`_inventory`, ~lines 198-228)
**Fix:** validate file count *before* the INSERT/commit, or wrap in a transaction that rolls back on the 422 path.
**Status:** OPEN

### COBALT-10 — Corrupt zip raises unhandled 500 and leaks a directory
`zipfile.ZipFile(tmp_path)` isn't wrapped for `zipfile.BadZipFile`. A
corrupted upload propagates as an unhandled 500, while the already-`mkdir`'d
extraction directory is left behind permanently with no DB row referencing it
— invisible to any cleanup path.
**Files:** `backend/routers/intake.py` (`_extract_zip`, ~line 140)
**Fix:** catch `zipfile.BadZipFile`, clean up the partial directory, return a real 422.
**Status:** OPEN

### COBALT-11 — Cross-process orphan-abort has no ownership check
`_abort_orphaned_runs` unconditionally marks *every* `RUNNING` row ABORTED on
any process startup — no PID/ownership tag distinguishes "this process's own
orphans" from "a genuinely live run in a sibling process." If process B
starts while process A is genuinely mid-migration on a *different* run_id,
B's startup falsely marks A's live run ABORTED in the DB while A's in-memory
task keeps running — and `_execute_run`'s completion write later overwrites
that ABORTED status to PASSED/FAILED with no record of the inconsistency.
**Files:** `backend/db.py:193-204` (`_abort_orphaned_runs`), `backend/routers/pipeline.py:203-207` (unconditional final status write)
**Fix:** tag each `migration_runs` row with the owning process's PID (from the new `.backend.pid` lockfile) at `/start` time; only abort rows owned by a PID that's no longer alive.
**Status:** OPEN

### COBALT-12 — Startup lockfile is advisory only, not a mutex
`.backend.pid` is overwritten unconditionally on every startup — it never
checks whether a previous process is still alive or has a live migration.
Explicitly documented as visibility-only in its own code comment. Two
colliding uvicorn instances still silently abort each other's in-flight runs.
**Files:** `backend/main.py:20-34`
**Fix:** on startup, if `.backend.pid`'s PID is still alive (`os.kill(pid, 0)`), refuse to start (or require `--force`) instead of silently overwriting.
**Status:** OPEN (partially mitigated by COBALT-11's PID-ownership fix)

### COBALT-13 — Same-run_id double-start is only single-process-safe
`_run_is_live` checks an in-memory dict — safe within one process, but two
uvicorn processes (the exact multi-session incident this session) each have
their own empty dict; both would call `execute_migration()` concurrently
against the same run_id's `work_items` rows with no DB-level lock.
**Files:** `backend/routers/pipeline.py:155-158` (`_run_is_live`)
**Fix:** add a DB-level advisory lock or a `locked_by_pid` column on `migration_runs`, checked/set atomically in `/start`.
**Status:** OPEN

### COBALT-14 — No alerting on terminal FAILED runs
A run that exhausts its repair budget just sits FAILED in the DB — no
webhook/email/Slack notification exists anywhere. The only way to discover a
FAILED run is polling `GET /migration/runs`.
**Files:** `backend/routers/pipeline.py:193-231` (`_execute_run`, `print()`-only error surfacing)
**Fix:** add a configurable webhook POST on terminal FAILED/ABORTED status.
**Status:** OPEN (explicitly requested by user this session, not yet built)

### COBALT-15 — Headless Write-tool path scoping unverified
`--disallowedTools Bash` blocks shell escape, but `Write` itself has no
directory scoping — a hallucinated absolute path from a compromised/malicious
prompt (e.g. prompt injection via attacker-crafted COBOL comments) could
theoretically Write outside `migration-state/runs/{run_id}/...`.
**Files:** `backend/llm.py` (all headless invocation call sites)
**Fix:** verify empirically (dynamic test: prompt a headless call to Write to an absolute path outside the run dir, confirm `--add-dir` scoping actually blocks it) rather than assume.
**Status:** NEEDS VERIFICATION (not confirmed exploitable, not confirmed safe)

---

## P2 — Real gaps, lower urgency

### COBALT-16 — Zero retention/cleanup for migration-state/runs/
No cron/admin endpoint/size-based eviction exists. Every run directory
(source + csharp output + agent workspaces, multi-hundred-MB each) persists
forever. Disk exhaustion is a "when," not an "if."
**Files:** n/a (missing feature)
**Fix:** add a retention policy (age- or count-based) and a cleanup endpoint/cron.
**Status:** OPEN

### COBALT-17 — print()-based error surfacing, no structured logging
Errors go to stdout via `print()` rather than a logger with levels/handlers —
no log-aggregation hook point for future alerting.
**Files:** `backend/routers/pipeline.py:214`
**Fix:** replace with Python `logging`, structured where practical.
**Status:** OPEN

### COBALT-18 — Multi-worker/horizontal-scaling assumption violated
`_run_state`/`_run_tasks` are process-local. Any deployment with >1 worker
sharing the DB breaks the live-run check (see COBALT-13).
**Files:** `backend/routers/pipeline.py:32-33`
**Fix:** same DB-level lock as COBALT-13 covers this; document single-worker-only until fixed.
**Status:** OPEN (duplicate root cause of COBALT-13)

---

## Verified clean (no action needed)

- **SQL injection:** every query found uses parameterized `?` placeholders — no string-interpolated SQL anywhere (orchestrator.py, db.py, routers/*.py).
- **Path traversal (non-symlink):** `_extract_zip`'s member-path check and `_read_file_under`'s `..`/absolute-path guard both correctly block escapes via `.resolve()` canonicalization. `assert_safe_rel` in `work_items.py` correctly rejects `..` for workspace paths.
- **repo_url SSRF (intake clone path):** `github_clone_url` correctly rejects non-https, non-github.com hosts, embedded credentials, and non-standard ports.
- **COBALT_MAX_AGENTS bound:** correctly clamped to `max(1, min(n, 8))`.
- **Credential handling in github-push:** the stored token is never logged, embedded in argv, or written to `.git/config` — clean, just used against an unvalidated destination (COBALT-2).
- **.gitignore coverage:** `migration-state/runs/`, `migration.db(+wal/shm)`, `.backend.pid` all correctly excluded from accidental `git add -A`.
- **`orchestrator.execute_migration`'s per-stage independent retry budget and never-give-up-on-transient-repair-crash behavior**: now covered by real (mocked, zero-cost) regression tests — `backend/tests/test_orchestrator_repair.py`, 3/3 passing.

## Test coverage — concrete next tests to write (not yet written)

From the test-coverage audit, in priority order, still open:
1. `test_set_item_status_matches_by_run_id_and_slug` — direct regression for the slug-based UPDATE match-key (a prior real bug: "silently updated 0 rows").
2. `test_abort_orphaned_runs_marks_running_as_aborted` — db.py:193, zero coverage today, mutates state on every process boot.
3. `test_execute_migration_resumes_interrupted_and_failed_items` — covers interrupted-item revival + failed-retry-reset + backfilled completed-item events.
4. `test_integrate_workspace_raises_on_missing_declared_path` — pure function, easy win.
5. `parity_gate.run_parity_gate` itself — zero tests found; currently only verified via live runs.
6. `llm.py`'s JSON-envelope parsing — pure logic, currently only exercised by real headless CLI calls in production.
