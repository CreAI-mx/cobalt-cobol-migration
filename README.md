# Cobalt — Agentic COBOL-to-C# Migration Platform

Cobalt is an agentic pipeline that migrates COBOL programs to a Clean
Architecture C# solution, with a real, deterministic parity gate (not just
`dotnet build`/`dotnet test`) verifying COBOL-vs-C# behavior byte-for-byte
before a migration is certified PASSED.

## Architecture

- **`backend/`** — FastAPI service (Python). `main.py` mounts `routers/intake.py`
  (source upload, file inventory, file preview) and `routers/pipeline.py`
  (migration lifecycle: plan, start, status, SSE event stream, artifact
  download, GitHub push). `orchestrator.py` runs the real pipeline:
  - **Planning** — a headless Claude Code session (`planner.py`) proposes a
    work-item manifest (conversion/persistence/cli/tests/documentation units),
    with a deterministic `work_items.fallback_plan()` if the planner call fails.
  - **Generating** — isolated headless Claude Code workers write each work
    item's C# files into a nested `src/{Domain,Application,Infrastructure,Cli}/`
    + `tests/Application.Tests/` Clean Architecture layout (`llm.py`).
  - **Building / Testing / Parity Validation** — a unified verify-then-repair
    loop (`_verify_chain` in `orchestrator.py`): `dotnet build`, `dotnet test`,
    then the real Phase 6 gate (`parity_gate.py`) — compiles each original
    `.cbl` program with GnuCOBOL as an oracle, runs the generated C# candidate
    against the same derived fixture, and byte-diffs the output. Any failure
    triggers a real headless-agent repair attempt (fed the actual compile
    error, test failure, or COBOL-vs-C# diff), with an independent retry
    budget per gate, before the chain re-verifies from Build forward.
  - **Documenting** — writes `README.md` + `docs/MIGRATION.md` into the
    generated solution.
- **`frontend/`** — React + TypeScript + Vite UI (served by the backend via
  `StaticFiles` in production — single process, one port). Walks the user
  through intake → plan review → live migration progress → parity results →
  artifact download.
- **`.claude/skills/`** — the skill documents (`SKILL.md`) each pipeline phase
  cites and reads at runtime via `--add-dir`, so an agent's cited procedure is
  real, not decorative.
- **`raw/`** — the demo COBOL fixture (`cobol-banking-systems.zip`) used for
  end-to-end verification: three programs (`ACCOUNT-LOOKUP`,
  `TRANSACTION-POSTING`, `AML-FLAGGING`) sharing one `accounts.dat` file.
- **`migration-state/schema.sql`** — the SQLite schema (`migration-state/migration.db`
  is created from this at runtime, not committed).

## Running locally

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8123
```

```bash
cd frontend
npm install
npm run build   # backend serves frontend/dist in production
```

Then `POST /migration/intake` (multipart `.zip` or `repo_url`), followed by
`POST /migration/{run_id}/start` to run the pipeline end-to-end.

### Configuring the Claude Code engine (required — every teammate needs their own)

Cobalt does NOT call the Anthropic API directly for Planning/Generating/
Repairing/Exploration's agentic steps — it spawns a **headless `claude -p`
subprocess** (`backend/llm.py::find_claude()` + `_claude_code_env()`). Each
teammate running this backend locally needs their OWN authenticated Claude
Code CLI session; there is no shared/bundled credential.

1. Install the Claude Code CLI and log in once, interactively:
   ```bash
   npm install -g @anthropic-ai/claude-code   # or your platform's install method
   claude   # run once, follow the login flow, then exit
   ```
2. Confirm the backend can find the binary — `find_claude()` checks, in
   order: the `CLAUDE_BIN` env var, then `claude` on `PATH`, then a hardcoded
   dev-machine fallback path that will NOT exist on your machine (it is
   specific to the original author's setup — do not rely on it). If `which
   claude` doesn't resolve after install, you MUST set
   `CLAUDE_BIN=/full/path/to/claude` in your `.env` (repo root) — without
   either PATH or CLAUDE_BIN, every headless call fails with "claude CLI not
   found", not a silent fallback to anyone else's binary.
3. Headless calls run under `HOME` (or `CLAUDE_HEADLESS_HOME` if you want to
   point them at a different, already-logged-in profile — e.g. a dedicated
   low-rate-limit account, useful if you also use `claude` interactively for
   other work and don't want the two sessions to compete for quota).
4. **Do not set `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, or
   `ANTHROPIC_AUTH_TOKEN` in the environment this backend runs in** unless
   you have also verified `_claude_code_env()` strips them (it does, as of
   this commit) — a set `ANTHROPIC_API_KEY` makes the `claude` CLI prioritize
   raw API-key auth over its own OAuth session, and can turn a healthy,
   already-logged-in Pro/Team account into "401 API key is invalid" for
   every headless call, mid-pipeline, with no code-level cause (verified
   live 2026-09-16: reproduced the exact failure by setting that one env var,
   fixed by never passing it through to the subprocess).
5. Symptom checklist if a teammate's headless calls fail and yours don't:
   - `claude -p "say hi" --max-turns 1` in their own shell, with their own
     `HOME` — if that alone fails, it's their CLI login, not Cobalt.
   - Check their shell for `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` set to
     anything, including an empty string (`env | grep ANTHROPIC`).
   - Confirm `CLAUDE_HEADLESS_HOME` (if set) actually points at a directory
     with a valid `.claude.json` session, not an empty/wrong profile.

### Building a generated solution manually (same dotnet as the backend)

From the **repo root**, load the SDK the parity sandbox uses (skips a broken
`/usr/bin/dotnet` when apt only installed `dotnet-host-*`):

```bash
source scripts/dotnet-env.sh
export PATH="$(pwd)/bin:$PATH"   # optional: same wrapper as below
```

With [direnv](https://direnv.net/), run `direnv allow` once — `.envrc` sources
that script when you `cd` into the repo.

```bash
cd migration-state/runs/{run_id}/csharp
dotnet build src/Cli/Cli.csproj
dotnet test tests/Application.Tests/Application.Tests.csproj
echo 1000000001 | dotnet run --project src/Cli/Cli.csproj --no-launch-profile -v q -- account-lookup
```

Or without sourcing: `/path/to/cobol/bin/dotnet build src/Cli/Cli.csproj`

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

## Known limitations (v1)

- Phase 6 parity fixtures exercise the happy path only — no negative-amount
  overpunch encoding, no multi-record files, no error-branch coverage.
- No support yet for COMP-3, VSAM/DB2, EBCDIC, or CALL-linked multi-program
  groups (compilation plumbing exists in `parity_gate.py` but is unexercised).
- `migration-cost-governance` skill exists but is not yet wired as a hard
  spend cap in the orchestrator.
