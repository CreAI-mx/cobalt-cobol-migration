#!/usr/bin/env bash
# Build/test/run a migrated solution without any manual DOTNET_ROOT/cd steps.
# Real gap found this session: a user had to manually export DOTNET_ROOT and
# cd into the run's csharp/ directory before any `dotnet` command worked,
# because the system's own `dotnet` (if any) may be missing libhostfxr.so or
# not installed at all — the backend already solves this via
# cobol_compilers.find_dotnet(), this script does the same for manual use.
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <run_id> [build|test|run <program>]"
  echo "  build            dotnet build src/Cli/Cli.csproj"
  echo "  test             dotnet test tests/Application.Tests/Application.Tests.csproj"
  echo "  run <program>    dotnet run --project src/Cli/Cli.csproj -- <program>"
  echo "  (no action)      build then test"
  exit 1
fi

run_id="$1"
shift || true
action="${1:-}"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
csharp_dir="$repo_root/migration-state/runs/$run_id/csharp"

if [ ! -d "$csharp_dir" ]; then
  echo "No generated C# at $csharp_dir — has this run finished Generating?" >&2
  exit 1
fi

if ! command -v dotnet >/dev/null 2>&1 || ! dotnet --version >/dev/null 2>&1; then
  # Same fallback path cobol_compilers.find_dotnet() uses on this machine —
  # kept in ONE place there; this mirrors it for manual/local use.
  fallback="/home/frg/.claude3_profile/.dotnet"
  if [ -x "$fallback/dotnet" ]; then
    export DOTNET_ROOT="$fallback"
    export PATH="$DOTNET_ROOT:$PATH"
    echo "(system dotnet unusable — using $fallback)"
  else
    echo "No working dotnet found on PATH or at the known fallback ($fallback)." >&2
    echo "Install .NET 8 SDK, or set DOTNET_ROOT yourself before running this script." >&2
    exit 1
  fi
fi

cd "$csharp_dir"

case "$action" in
  build) dotnet build src/Cli/Cli.csproj ;;
  test)  dotnet test tests/Application.Tests/Application.Tests.csproj ;;
  run)
    program="${2:?Usage: $0 <run_id> run <program-name>}"
    dotnet run --project src/Cli/Cli.csproj -- "$program"
    ;;
  "")
    dotnet build src/Cli/Cli.csproj
    dotnet test tests/Application.Tests/Application.Tests.csproj
    ;;
  *)
    echo "Unknown action: $action" >&2
    exit 1
    ;;
esac
