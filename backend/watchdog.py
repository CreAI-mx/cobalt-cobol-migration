"""Stuck-run watchdog: an in-process asyncio background task (started from
main.py's lifespan, NOT an external process) that periodically checks for
migration_runs/exploration_sessions rows stuck at status='RUNNING' whose
owning asyncio.Task is no longer alive in THIS process's memory.

Why in-process, not an external script: `_run_is_live`/`_exploration_is_live`
read `_run_tasks`/`_exploration_tasks`, plain in-memory dicts of live
asyncio.Task objects private to the backend's own process. An external
watcher process has no way to see those dicts short of adding IPC (a second
API endpoint just to expose task liveness, or a heartbeat file) — that's
strictly more moving parts for the same answer this process already knows
for free. The known failure mode this targets (task died mid-run — silent
crash, unhandled exception, a DB-lock write inside the crash handler itself
also failing) leaves the row RUNNING with NO live task in the SAME process
that started it; `_abort_orphaned_runs` in db.py already covers the sibling
case (row RUNNING when a NEW process starts, i.e. after a restart) but only
runs once at startup and only for migration_runs. This complements it by
running continuously, in both tables.

Auto-retry is capped at 1 per run_id (counted from watchdog_events, so the
cap survives a process restart) specifically so a run that fails every time
for a real reason (bad COBOL input, a genuine bug) does not retry forever —
after the cap is spent, orphaned rows are marked FAILED and left alone.
"""
import asyncio
import traceback
from datetime import datetime, timezone

from db import open_db
from ulid import ULID

WATCHDOG_INTERVAL_SECONDS = 45
MAX_AUTO_RETRIES = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _log(conn, run_id: str, kind: str, action: str, detail: str) -> None:
    await conn.execute(
        "INSERT INTO watchdog_events (event_id, run_id, kind, action, detail, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (str(ULID()), run_id, kind, action, detail, _now()),
    )
    await conn.commit()
    print(f"[watchdog] run_id={run_id} kind={kind} action={action} detail={detail}", flush=True)


async def _retry_count(conn, run_id: str) -> int:
    cur = await conn.execute(
        "SELECT COUNT(*) FROM watchdog_events WHERE run_id = ? AND action = 'auto_retry'",
        (run_id,),
    )
    row = await cur.fetchone()
    return int(row[0]) if row else 0


async def _check_pipeline_runs(conn) -> None:
    # Imported lazily to avoid a circular import at module load time
    # (routers.pipeline imports db, db must not import routers.pipeline).
    from routers import pipeline as pipeline_router

    cur = await conn.execute("SELECT run_id FROM migration_runs WHERE status = 'RUNNING'")
    rows = await cur.fetchall()
    for (run_id,) in rows:
        if pipeline_router._run_is_live(run_id):
            continue
        retries = await _retry_count(conn, run_id)
        await conn.execute(
            "UPDATE migration_runs SET status = 'FAILED', finished_at = ? WHERE run_id = ?",
            (_now(), run_id),
        )
        await conn.commit()
        await _log(
            conn, run_id, "pipeline", "marked_failed",
            f"status=RUNNING but no live task in this process (retries_used={retries})",
        )
        if retries >= MAX_AUTO_RETRIES:
            await _log(
                conn, run_id, "pipeline", "retry_skipped_cap",
                f"auto-retry cap ({MAX_AUTO_RETRIES}) already spent — leaving FAILED",
            )
            continue
        await conn.execute(
            "UPDATE migration_runs SET status = 'RUNNING', finished_at = NULL WHERE run_id = ?",
            (run_id,),
        )
        await conn.commit()
        pipeline_router._run_state.setdefault(run_id, [])
        pipeline_router._run_tasks[run_id] = asyncio.create_task(
            pipeline_router._execute_run(run_id)
        )
        await _log(conn, run_id, "pipeline", "auto_retry", "re-launched _execute_run")


async def _check_exploration_sessions(conn) -> None:
    from routers import exploration as exploration_router

    cur = await conn.execute("SELECT run_id FROM exploration_sessions WHERE status = 'RUNNING'")
    rows = await cur.fetchall()
    for (run_id,) in rows:
        if exploration_router._exploration_is_live(run_id):
            continue
        retries = await _retry_count(conn, run_id)
        await conn.execute(
            "UPDATE exploration_sessions SET status = 'FAILED', finished_at = ? WHERE run_id = ?",
            (_now(), run_id),
        )
        await conn.commit()
        await _log(
            conn, run_id, "exploration", "marked_failed",
            f"status=RUNNING but no live task in this process (retries_used={retries})",
        )
        if retries >= MAX_AUTO_RETRIES:
            await _log(
                conn, run_id, "exploration", "retry_skipped_cap",
                f"auto-retry cap ({MAX_AUTO_RETRIES}) already spent — leaving FAILED",
            )
            continue
        await conn.execute(
            "UPDATE exploration_sessions SET status = 'RUNNING', finished_at = NULL WHERE run_id = ?",
            (run_id,),
        )
        await conn.commit()
        task = asyncio.create_task(exploration_router._execute_exploration(run_id))
        exploration_router._exploration_tasks[run_id] = task

        def _done(_t: asyncio.Task, _run_id: str = run_id) -> None:
            exploration_router._exploration_tasks.pop(_run_id, None)

        task.add_done_callback(_done)
        await _log(conn, run_id, "exploration", "auto_retry", "re-launched _execute_exploration")


async def watchdog_tick() -> None:
    """One full sweep — pipeline runs then exploration sessions, each on its
    own connection/commit so one table's failure never blocks the other."""
    conn = await open_db()
    try:
        try:
            await _check_pipeline_runs(conn)
        except Exception:
            print(f"[watchdog] pipeline sweep crashed:\n{traceback.format_exc()}", flush=True)
        try:
            await _check_exploration_sessions(conn)
        except Exception:
            print(f"[watchdog] exploration sweep crashed:\n{traceback.format_exc()}", flush=True)
    finally:
        await conn.close()


async def watchdog_loop() -> None:
    """Started as an asyncio.create_task in main.py's lifespan; cancelled on
    shutdown like the existing per-run snapshot loops in routers/pipeline.py."""
    try:
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
            await watchdog_tick()
    except asyncio.CancelledError:
        raise
