#!/usr/bin/env bash
# One-shot local setup for Cobalt (backend + frontend), macOS and Linux.
# Does NOT install cobc/dotnet/claude — those are real external tools with
# their own installers; this script checks for them and tells you what's
# missing instead of silently masking a broken environment.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
os_name="$(uname -s)"

echo "== Cobalt setup ($os_name) =="

check_tool() {
  local name="$1" hint="$2"
  if command -v "$name" >/dev/null 2>&1; then
    echo "  [ok] $name -> $(command -v "$name")"
  else
    echo "  [MISSING] $name — $hint"
  fi
}

echo "-- Checking external tools (required to run a real migration) --"
check_tool python3 "install Python 3.11+ (brew install python3 / apt install python3)"
check_tool node    "install Node 18+ (brew install node / apt install nodejs npm)"
check_tool claude  "install Claude Code CLI and log in: https://docs.claude.com/claude-code"
check_tool cobc    "install GnuCOBOL (brew install gnu-cobol / apt install gnucobol) — required for the real Phase 6 parity gate"
check_tool dotnet  "install .NET SDK 8 (https://dotnet.microsoft.com/download) — required to build/test generated C#"

echo
echo "-- Backend (Python) --"
cd "$repo_root/backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
".venv/bin/pip" install --quiet --upgrade pip
".venv/bin/pip" install --quiet -r requirements.txt
echo "  backend venv ready: backend/.venv"

echo
echo "-- Frontend (Node) --"
cd "$repo_root/frontend"
npm install --silent
echo "  frontend deps installed"

echo
echo "== Done =="
echo "Run the backend:  cd backend && .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8123"
echo "Build the UI:     cd frontend && npm run build   (backend serves frontend/dist)"
echo
echo "If any external tool above is [MISSING], the pipeline will still start but"
echo "will fail at the step that needs it (Building needs dotnet, Parity Validation"
echo "needs cobc, Generating needs an authenticated claude CLI session)."
echo
echo "Optional env vars (see backend/llm.py, backend/cobol_compilers.py):"
echo "  CLAUDE_BIN            — path to the claude CLI, if not on PATH"
echo "  CLAUDE_HEADLESS_HOME  — HOME dir for the headless claude subprocess"
echo "                          (defaults to your own HOME; only needed if you"
echo "                          want the pipeline to authenticate as a different"
echo "                          Claude Code profile than your interactive shell)"
echo "  COBALT_MAX_AGENTS     — concurrent headless workers (default 3)"
