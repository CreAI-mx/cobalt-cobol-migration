"""FastAPI app — single source of truth for both human UI and agentic API.
Serves the intake page at / and OpenAPI (the agentic entry point) at /docs for free."""
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from db import init_db, DB_PATH
from routers import intake, pipeline

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
    yield


app = FastAPI(
    title="COBOL to C# Migration Platform",
    description="Intake + pipeline API. Humans use the / page; agents drive the "
                "same pipeline via this REST API — see /openapi.json.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(intake.router)
app.include_router(pipeline.router)


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
