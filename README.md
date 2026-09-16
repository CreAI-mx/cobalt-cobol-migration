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

### Building a generated solution manually

If you want to `dotnet build`/`dotnet run` a migrated solution yourself
(`migration-state/runs/{run_id}/csharp/`) and your system's own `dotnet`
isn't installed or is missing `libhostfxr.so`, point `DOTNET_ROOT` at
whichever real .NET 8 SDK install the backend itself uses
(`cobol_compilers.find_dotnet()` — check `_DOTNET_FALLBACKS` for the exact
path on this machine) before running any `dotnet` command:

```bash
export DOTNET_ROOT="<path from find_dotnet()>"
export PATH="$DOTNET_ROOT:$PATH"
cd migration-state/runs/{run_id}/csharp
dotnet build src/Cli/Cli.csproj
dotnet test tests/Application.Tests/Application.Tests.csproj
dotnet run --project src/Cli/Cli.csproj -- account-lookup   # one command per line — do not paste multiple dotnet run lines together, stdin routing between them is undefined
```

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
