"""FastAPI app — single source of truth for both human UI and agentic API.
Serves the intake page at / and OpenAPI (the agentic entry point) at /docs for free."""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from dotenv import load_dotenv
# Real bug found 2026-09-16: repo-root .env (ANTHROPIC_API_KEY for the
# Exploration subsystem's agentic Phase 2 via Strands) was never loaded —
# nothing in this process ever read it, so the agent silently fell back to
# deterministic drafts forever. override=False: an operator's real shell
# env var still wins over .env, this only fills gaps.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
# Claude Code's own shell sets ANTHROPIC_BASE_URL="" (empty, not unset) —
# the real Anthropic SDK (used directly by Strands/exploration's agentic
# business-rule extraction) then builds a base URL with no scheme and every
# call fails with a generic "Connection error." (found live, 2026-09-16).
# Real regression found later the same day: popping ANTHROPIC_AUTH_TOKEN
# alongside it broke the headless `claude -p` repair agents (orchestrator.py,
# llm.py) — they need that token for their OWN auth flow, distinct from the
# direct Anthropic SDK. Every repair attempt failed 401 until this was
# narrowed back to ONLY the base URL.
os.environ.pop("ANTHROPIC_BASE_URL", None)

import llm
import watchdog
from db import init_db, DB_PATH
from routers import intake, pipeline, exploration

# React build output (frontend/dist). The old Jinja2 template at
# templates/index.html stays on disk as reference but is no longer routed.
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

# 2026-09-16: this backend was killed and restarted by an unrelated concurrent
# process at least twice in one session, silently ABORTing real in-flight
# migration runs each time (each restart's own process had no memory of the
# other's live run). This lockfile can't PREVENT that — two independent
# processes on the same dev box can always `kill` each other — but it makes a
# live process visible before someone does: `cat migration-state/.backend.pid`
# shows the current PID, when it started, and a reminder to check
# GET /migration/runs for a live run first.
_LOCKFILE = Path(DB_PATH).parent / ".backend.pid"


def _write_startup_lockfile() -> None:
    _LOCKFILE.write_text(
        f"pid={os.getpid()}\n"
        f"started_at={datetime.now(timezone.utc).isoformat()}\n"
        f"# Before killing this process: GET /migration/runs and check for any\n"
        f"# row with status=RUNNING — killing this process ABORTs it immediately.\n"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _write_startup_lockfile()
    await init_db()
    # Stuck-run watchdog (backend/watchdog.py): catches a run that goes
    # RUNNING-with-no-live-task WITHIN this same process's lifetime (silent
    # task crash, a DB-lock write failing inside the crash handler itself) —
    # the sibling case to _abort_orphaned_runs (db.py), which only catches a
    # RUNNING row left over from a PREVIOUS process at startup.
    watchdog_task = asyncio.create_task(watchdog.watchdog_loop())
    yield
    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass
    # COBALT-5 (audit 2026-09-16): a graceful `uvicorn` shutdown (SIGTERM) now
    # kills any still-running `claude -p` headless children instead of
    # orphaning them to init. Does NOT help on `kill -9`/crash (no shutdown
    # handler runs at all in that case) — that gap is the tradeoff of not
    # doing full process-group isolation; documented, not silently ignored.
    killed = llm.kill_all_active_headless_processes()
    if killed:
        print(f"[shutdown] killed {killed} orphaned headless claude process(es)", flush=True)


app = FastAPI(
    title="COBOL to C# Migration Platform",
    description="Intake + pipeline API. Humans use the / page; agents drive the "
                "same pipeline via this REST API — see /openapi.json.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(intake.router)
app.include_router(pipeline.router)
app.include_router(exploration.router)

# COBALT-1 (audit 2026-09-16): every /migration/* endpoint — including
# github-push, which uses this machine's real stored GitHub credential, and
# file preview, which can read a client's uploaded COBOL source — had zero
# authentication. Opt-in for now (unset COBALT_API_KEY preserves today's
# local-dev-only behavior with no header required) rather than breaking the
# existing UI, which does not yet send this header; set COBALT_API_KEY and
# have any real deployment's reverse proxy inject the matching header, or
# update the frontend to send it, before exposing this port beyond localhost.
_API_KEY = os.environ.get("COBALT_API_KEY")


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if _API_KEY and request.url.path.startswith("/migration"):
        if request.headers.get("X-Cobalt-Api-Key") != _API_KEY:
            return JSONResponse({"detail": "missing or invalid X-Cobalt-Api-Key"}, status_code=401)
    return await call_next(request)


@app.get("/")
async def spa_index(_: Request) -> FileResponse:
    """Always revalidate the wizard shell so a 2-step bundle cannot stick."""
    return FileResponse(
        FRONTEND_DIST / "index.html",
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# Mounted last so API routes above take precedence; html=True serves index.html at /.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
