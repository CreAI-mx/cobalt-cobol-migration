"""FastAPI app — single source of truth for both human UI and agentic API.
Serves the intake page at / and OpenAPI (the agentic entry point) at /docs for free."""
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from db import init_db
from routers import intake, pipeline

# React build output (frontend/dist). The old Jinja2 template at
# templates/index.html stays on disk as reference but is no longer routed.
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
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
