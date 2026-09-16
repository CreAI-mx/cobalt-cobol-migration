"""Phase 0 (cobol-discovery) made real: accepts a zip OR a GitHub repo URL,
extracts/clones it, walks the tree, inventories EVERY file (whole-project
scope) with sha256/LOC and a file_kind discriminator; PROGRAM-ID extracted for
COBOL source only — no LLM here, pure deterministic parsing per
.claude/skills/cobol-discovery/SKILL.md."""
import asyncio
import hashlib
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from ulid import ULID  # python-ulid
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
import aiosqlite

from db import get_db
from models import IntakeResponse, SourceFileView, TreeNode

router = APIRouter(prefix="/migration", tags=["intake"])

COBOL_EXTS = {".cob", ".cbl", ".cpy"}
COBOL_SOURCE_EXTS = {".cob", ".cbl"}
COPYBOOK_EXTS = {".cpy"}
DOC_EXTS = {".md", ".txt", ".rst", ".adoc", ".pdf", ".doc", ".docx"}
# Cobalt migrates backend only (explicit user directive). Anything that looks
# like UI/frontend in the source estate is inventoried but never converted.
FRONTEND_DIR_MARKERS = {"frontend", "ui", "web", "webapp", "client", "wwwroot", "public"}
FRONTEND_EXTS = {".html", ".htm", ".css", ".scss", ".sass", ".less", ".jsx", ".tsx", ".vue", ".svelte"}
PROGRAM_ID_RE = re.compile(r"PROGRAM-ID\.\s*([A-Za-z0-9_-]+)", re.IGNORECASE)
GITHUB_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def classify_file_kind(path: str) -> str:
    """Discriminator for the (unrenamed) cobol_files table now that intake
    inventories the whole project: cobol_source | copybook | frontend | doc | other."""
    suffix = Path(path).suffix.lower()
    if suffix in COBOL_SOURCE_EXTS:
        return "cobol_source"
    if suffix in COPYBOOK_EXTS:
        return "copybook"
    dir_parts = {p.lower() for p in Path(path).parts[:-1]}
    if suffix in FRONTEND_EXTS or dir_parts & FRONTEND_DIR_MARKERS:
        return "frontend"
    if suffix in DOC_EXTS:
        return "doc"
    return "other"

# Banking COBOL estates are large. Stream the zip to disk; do not load it into RAM
# and do not reject a source for being "too big" at 20 MB.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024       # 2 GB raw zip
MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024  # 8 GB decompressed (zip-bomb guard only)
GIT_CLONE_TIMEOUT_S = 600

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"


def github_clone_url(raw: str) -> str:
    """Accept only https://github.com/owner/repo. No SSH, credentials, or extra hosts."""
    text = raw.strip()
    if not text:
        raise HTTPException(400, "Paste a GitHub repository URL.")
    if text.startswith("git@"):
        raise HTTPException(400, "SSH URLs are not accepted. Use https://github.com/owner/repo")
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    parsed = urlparse(text)
    if parsed.scheme != "https":
        raise HTTPException(400, "Only https GitHub URLs are accepted.")
    if parsed.hostname not in ("github.com", "www.github.com"):
        raise HTTPException(400, "Only github.com repositories are accepted.")
    if parsed.username or parsed.password or parsed.port:
        raise HTTPException(400, "Credentials and custom ports are not allowed.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise HTTPException(400, "URL must look like https://github.com/owner/repo")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    # /tree/branch, /archive/..., blob URLs — still clone owner/repo
    if repo in {".", ".."} or not GITHUB_OWNER_RE.match(owner) or not GITHUB_REPO_RE.match(repo):
        raise HTTPException(400, "Invalid GitHub owner or repository name.")
    return f"https://github.com/{owner}/{repo}.git"


def _build_tree(root: Path) -> TreeNode:
    def walk(p: Path) -> TreeNode:
        if p.is_dir():
            children = sorted(
                (walk(c) for c in p.iterdir() if not c.name.startswith(".")),
                key=lambda n: (n.type != "dir", n.name.lower()),
            )
            return TreeNode(name=p.name, type="dir", children=children)
        is_cobol = p.suffix.lower() in COBOL_EXTS
        return TreeNode(name=p.name, type="file", is_cobol=is_cobol)

    return walk(root)


def _flatten_files(root: TreeNode):
    """Yield ALL file paths relative to the extraction root (whole-project scope,
    not COBOL-only). root.name itself (== extract_dir's own directory name) is
    never part of the path — only descend into its children."""
    def walk(node: TreeNode, prefix: str):
        path = f"{prefix}{node.name}"
        if node.type == "file":
            yield path
        for child in node.children or []:
            yield from walk(child, path + "/")

    for child in root.children or []:
        yield from walk(child, "")


async def _extract_zip(upload: UploadFile, extract_dir: Path) -> None:
    if not upload.filename or not upload.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Only .zip is supported for extraction. "
                                  ".rar cannot be unpacked server-side without a "
                                  "non-free library — convert to .zip first.")

    written = 0
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit"
                    )
                tmp.write(chunk)
        with zipfile.ZipFile(tmp_path) as zf:
            resolved_root = extract_dir.resolve()
            total_uncompressed = 0
            for member in zf.infolist():
                target = (extract_dir / member.filename).resolve()
                if not target.is_relative_to(resolved_root):
                    raise HTTPException(400, f"Unsafe path in archive: {member.filename}")
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        413,
                        f"Archive exceeds {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB uncompressed limit",
                    )
            zf.extractall(extract_dir)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


async def _clone_github(clone_url: str, extract_dir: Path) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["GIT_ASKPASS"] = "echo"
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-c", "core.sshCommand=/bin/false",
        "clone",
        "--depth", "1",
        "--single-branch",
        "--",
        clone_url,
        str(extract_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=GIT_CLONE_TIMEOUT_S)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise HTTPException(504, f"Git clone timed out after {GIT_CLONE_TIMEOUT_S}s.")
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()[:280]
        raise HTTPException(400, f"Could not clone repository. {detail or 'git clone failed.'}")


async def _inventory(
    conn: aiosqlite.Connection, run_id: str, extract_dir: Path, source_repo: str
) -> IntakeResponse:
    tree = _build_tree(extract_dir)
    all_paths = list(_flatten_files(tree))

    started_at = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        "INSERT INTO migration_runs (run_id, started_at, status, target_lang, source_repo) "
        "VALUES (?, ?, 'RUNNING', 'csharp', ?)",
        (run_id, started_at, source_repo),
    )

    total_files = 0
    cobol_files = 0
    for rel_path in all_paths:
        kind = classify_file_kind(rel_path)
        full_path = extract_dir / rel_path
        content = full_path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        loc = content.count(b"\n") + 1
        program_id = None
        if kind == "cobol_source":
            m = PROGRAM_ID_RE.search(content.decode("utf-8", errors="replace"))
            program_id = m.group(1) if m else None
        await conn.execute(
            "INSERT INTO cobol_files (file_id, run_id, path, program_id, loc, sha256, file_kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(ULID()), run_id, rel_path, program_id, loc, sha256, kind),
        )
        total_files += 1
        if kind in ("cobol_source", "copybook"):
            cobol_files += 1

    await conn.commit()

    if total_files == 0:
        raise HTTPException(422, "Source contains no files.")

    return IntakeResponse(run_id=run_id, total_files=total_files, cobol_files=cobol_files, tree=tree)


@router.post("/intake", response_model=IntakeResponse)
async def intake(
    file: UploadFile | None = File(None),
    repo_url: str | None = Form(None),
    conn: aiosqlite.Connection = Depends(get_db),
):
    has_file = bool(file is not None and file.filename)
    repo = (repo_url or "").strip()
    # URL wins: a leftover zip in the file input must not steal a GitHub paste
    # and hit the zip size path.
    if has_file and repo:
        has_file = False
    if not has_file and not repo:
        raise HTTPException(400, "Drop a .zip or paste a GitHub repository URL.")

    run_id = str(ULID())
    extract_dir = RUNS_DIR / run_id / "source"

    if has_file:
        extract_dir.mkdir(parents=True, exist_ok=True)
        await _extract_zip(file, extract_dir)
        source_repo = str(extract_dir)
    else:
        clone_url = github_clone_url(repo)
        extract_dir.parent.mkdir(parents=True, exist_ok=True)
        await _clone_github(clone_url, extract_dir)
        source_repo = clone_url

    return await _inventory(conn, run_id, extract_dir, source_repo)


@router.get("/runs")
async def list_runs(conn: aiosqlite.Connection = Depends(get_db), limit: int = 20):
    """Execution history for the Onboarding screen — real runs, most recent
    first. `live` is the in-memory pipeline task (lazy import avoids a cycle
    with routers.pipeline)."""
    from routers.pipeline import _run_is_live
    cursor = await conn.execute(
        "SELECT r.run_id, r.started_at, r.finished_at, r.status, r.source_repo, r.target_lang, "
        "       COUNT(f.file_id) AS total_files, "
        "       SUM(CASE WHEN f.file_kind = 'cobol_source' THEN 1 ELSE 0 END) AS cobol_files "
        "FROM migration_runs r LEFT JOIN cobol_files f ON f.run_id = r.run_id "
        "GROUP BY r.run_id ORDER BY r.started_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "run_id": r[0], "started_at": r[1], "finished_at": r[2], "status": r[3],
            "source_repo": r[4], "target_lang": r[5],
            "total_files": r[6] or 0, "cobol_files": r[7] or 0,
            "live": _run_is_live(r[0]),
        }
        for r in rows
    ]


@router.get("/{run_id}/tree", response_model=TreeNode)
async def get_tree(run_id: str):
    source_dir = RUNS_DIR / run_id / "source"
    if not source_dir.exists():
        raise HTTPException(404, f"No extracted source found for run_id={run_id}")
    return _build_tree(source_dir)


_MAX_PREVIEW_BYTES = 200_000


def _generated_path_candidates(path: str) -> list[str]:
    """Map After-tree paths (src/..., tests/...) to files under run/csharp/."""
    rel = Path(path)
    posix = rel.as_posix()
    out: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        if p and p not in seen:
            seen.add(p)
            out.append(p)

    add(posix)
    parts = rel.parts
    if parts and parts[0] == "src":
        add(str(Path(*parts[1:])).replace("\\", "/"))
    if parts and parts[0] == "tests":
        add(str(Path(*parts[1:])).replace("\\", "/"))
    return out


def _generated_search_bases(run_id: str) -> list[Path]:
    """Integrated csharp/ first, then each worker workspace out/ (pre-integrate)."""
    run_root = RUNS_DIR / run_id
    bases: list[Path] = [run_root / "csharp"]
    ws_root = run_root / "workspaces"
    if ws_root.is_dir():
        for item in sorted(ws_root.iterdir()):
            if not item.is_dir():
                continue
            out = item / "out"
            if out.is_dir():
                bases.append(out)
    return bases


def _read_file_under(base_dir: Path, run_id: str, path: str, not_found_hint: str) -> SourceFileView:
    """Shared path-traversal-safe read for both the source tree and the
    generated C# output — same guard, different root."""
    resolved_base = base_dir.resolve()
    if not resolved_base.exists():
        raise HTTPException(404, f"{not_found_hint} for run_id={run_id}")
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix().startswith("/"):
        raise HTTPException(400, "path must be relative and stay inside the tree")
    target = (resolved_base / rel).resolve()
    if resolved_base not in target.parents and target != resolved_base:
        raise HTTPException(400, "path escapes the tree")
    if not target.is_file():
        raise HTTPException(404, f"No file at {path}")

    raw = target.read_bytes()
    truncated = len(raw) > _MAX_PREVIEW_BYTES
    blob = raw[:_MAX_PREVIEW_BYTES]
    kind = classify_file_kind(path)
    if b"\x00" in blob[:4096]:
        return SourceFileView(
            path=path, kind=kind, content="", loc=0, truncated=truncated, binary=True,
        )
    text = blob.decode("utf-8", errors="replace")
    program_id = None
    if kind in ("cobol_source", "copybook"):
        m = PROGRAM_ID_RE.search(text)
        if m:
            program_id = m.group(1)
    return SourceFileView(
        path=path, kind=kind, content=text, loc=text.count("\n") + 1,
        truncated=truncated, binary=False, program_id=program_id,
    )


@router.get("/{run_id}/file", response_model=SourceFileView)
async def get_source_file(run_id: str, path: str):
    """Origin file preview for the HITL modal. Reads the real intake copy.
    Never invents contents. Path is relative to the run source root."""
    return _read_file_under(
        RUNS_DIR / run_id / "source", run_id, path, "No extracted source found",
    )


@router.get("/{run_id}/generated-file", response_model=SourceFileView)
async def get_generated_file(run_id: str, path: str):
    """Real generated-C# preview — reads whatever Phase 4/5 actually wrote to
    disk. Distinct from get_source_file: without this, clicking a 'done' node
    in the After tree had nothing real to show (only the pre-generation
    proposal brief), even though the file genuinely exists on disk by then."""
    last_err: HTTPException | None = None
    for base in _generated_search_bases(run_id):
        for candidate in _generated_path_candidates(path):
            try:
                return _read_file_under(base, run_id, candidate, "No generated output found")
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                last_err = exc
    if last_err:
        raise last_err
    raise HTTPException(404, f"No generated output found for run_id={run_id}")
