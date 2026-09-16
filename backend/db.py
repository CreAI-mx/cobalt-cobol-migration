"""SQLite connection helper. Reuses migration-state/schema.sql as-is — no schema
redefinition here. One connection per request via FastAPI dependency injection."""
import os
import aiosqlite

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_ROOT, "migration-state", "migration.db")
SCHEMA_PATH = os.path.join(REPO_ROOT, "migration-state", "schema.sql")


async def init_db() -> None:
    """Create migration.db from schema.sql if it doesn't exist yet, then apply
    in-place migrations. Idempotent."""
    is_new = not os.path.exists(DB_PATH)
    async with aiosqlite.connect(DB_PATH) as conn:
        if is_new:
            with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
                await conn.executescript(f.read())
            await conn.commit()
        await _migrate_file_kind(conn)
        await _migrate_suggested_component_name(conn)
        await _migrate_gate_decisions(conn)
        await _abort_orphaned_runs(conn)
        await _migrate_architecture_decisions(conn)
        await _migrate_run_events(conn)
        await _migrate_work_items(conn)


async def _migrate_file_kind(conn: aiosqlite.Connection) -> None:
    """Scope change: intake now inventories ALL files, not just COBOL. cobol_files
    keeps its name (schema stability) but gains a file_kind discriminator:
    'cobol_source' | 'copybook' | 'doc' | 'other'. Idempotent via PRAGMA check.
    Pre-migration rows were COBOL-ext only, so default 'cobol_source' and backfill
    copybooks by extension."""
    cursor = await conn.execute("PRAGMA table_info(cobol_files)")
    columns = [row[1] for row in await cursor.fetchall()]
    if "file_kind" in columns:
        return
    await conn.execute(
        "ALTER TABLE cobol_files ADD COLUMN file_kind TEXT NOT NULL DEFAULT 'cobol_source'"
    )
    await conn.execute(
        "UPDATE cobol_files SET file_kind = 'copybook' WHERE lower(path) LIKE '%.cpy'"
    )
    await conn.commit()


async def _migrate_suggested_component_name(conn: aiosqlite.Connection) -> None:
    """Phase 2 (LLM extraction) also produces a behavior-derived PascalCase C#
    component name per file — the frontend Step 3 proposal consumes it. Schema.sql
    predates this; add the column idempotently."""
    cursor = await conn.execute("PRAGMA table_info(business_logic_extracts)")
    columns = [row[1] for row in await cursor.fetchall()]
    if "suggested_component_name" in columns:
        return
    await conn.execute(
        "ALTER TABLE business_logic_extracts ADD COLUMN suggested_component_name TEXT"
    )
    await conn.commit()


async def _migrate_gate_decisions(conn: aiosqlite.Connection) -> None:
    """Human Approval Gate (Phase 7): a decision + comment must persist so the
    pipeline team sees rejection feedback, not just a client-side flag."""
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='gate_decisions'"
    )
    if await cursor.fetchone():
        return
    await conn.execute(
        """CREATE TABLE gate_decisions (
            decision_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES migration_runs(run_id),
            decision TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    await conn.commit()


async def _migrate_architecture_decisions(conn: aiosqlite.Connection) -> None:
    """HITL architecture workshop (Step 3): shape + directive + accept/recreate.
    Phase 4 waits until action='accepted'. Append-only revisions."""
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='architecture_decisions'"
    )
    if await cursor.fetchone():
        return
    await conn.execute(
        """CREATE TABLE architecture_decisions (
            decision_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES migration_runs(run_id),
            revision INTEGER NOT NULL,
            shape TEXT NOT NULL,
            directive TEXT,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    await conn.commit()


async def _migrate_run_events(conn: aiosqlite.Connection) -> None:
    """Periodic snapshot of the (memory-only) live event log — _run_state dies
    with the process, so a past/aborted run had NO way to be inspected after a
    restart. This table is what makes run history clickable/interactive
    (monitor 'which phase is run X stuck at') instead of just a status badge."""
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='run_events'"
    )
    if await cursor.fetchone():
        return
    await conn.execute(
        """CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES migration_runs(run_id),
            seq INTEGER NOT NULL,
            type TEXT NOT NULL,
            phase TEXT NOT NULL,
            file_path TEXT,
            status TEXT NOT NULL,
            detail TEXT,
            skill TEXT
        )"""
    )
    await conn.execute("CREATE INDEX idx_run_events_run ON run_events(run_id, seq)")
    await conn.commit()


async def _migrate_work_items(conn: aiosqlite.Connection) -> None:
    """Manifest + isolated work items. Idempotent. Callers: init_db."""
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_plans'"
    )
    if await cursor.fetchone():
        return
    await conn.execute(
        """CREATE TABLE migration_plans (
            plan_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES migration_runs(run_id),
            summary TEXT NOT NULL,
            solution_name TEXT NOT NULL,
            stage TEXT NOT NULL,
            ui_blocks_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    await conn.execute(
        """CREATE TABLE work_items (
            work_item_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES migration_runs(run_id),
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            source_paths_json TEXT NOT NULL,
            expected_paths_json TEXT NOT NULL,
            depends_on_json TEXT NOT NULL,
            wave INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            workspace_rel TEXT,
            agent_id TEXT,
            error TEXT,
            started_at TEXT,
            finished_at TEXT
        )"""
    )
    await conn.execute(
        """CREATE TABLE work_item_artifacts (
            artifact_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL REFERENCES work_items(work_item_id),
            run_id TEXT NOT NULL REFERENCES migration_runs(run_id),
            declared_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            integrated INTEGER NOT NULL DEFAULT 0
        )"""
    )
    await conn.execute("CREATE INDEX idx_work_items_run ON work_items(run_id)")
    await conn.commit()


async def open_db() -> aiosqlite.Connection:
    """Owned connection for background pipeline tasks — get_db() closes when
    the HTTP request ends, which would kill a fire-and-forget /start job."""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    return conn


async def _abort_orphaned_runs(conn: aiosqlite.Connection) -> None:
    """A run stuck in RUNNING when this process starts belonged to a PREVIOUS
    server process (restarted while a pipeline was mid-flight — happened
    repeatedly this session). The in-memory _run_state/asyncio task is gone;
    the DB row must not lie forever. Mark it ABORTED honestly, not silently."""
    from datetime import datetime, timezone
    await conn.execute(
        "UPDATE migration_runs SET status = 'ABORTED', finished_at = ? "
        "WHERE status = 'RUNNING'",
        (datetime.now(timezone.utc).isoformat(),),
    )
    await conn.commit()


async def get_db():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        await conn.close()
