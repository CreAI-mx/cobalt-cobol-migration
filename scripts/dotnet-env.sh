#!/usr/bin/env bash
# Same dotnet resolution as backend/cobol_compilers.find_dotnet()

_COBALT_DOTNET_FALLBACKS=(
  "/home/frg/.claude3_profile/.dotnet/dotnet"
)

_cobalt_dotnet_usable() {
  local d="$1"
  [[ -n "$d" && -x "$d" ]] || return 1
  local root
  root="$(cd "$(dirname "$d")" && pwd)"
  env DOTNET_ROOT="$root" PATH="$root:${PATH:-}" "$d" --version >/dev/null 2>&1
}

cobalt_resolve_dotnet() {
  local candidates=() c w seen=""
  w="$(command -v dotnet 2>/dev/null || true)"
  [[ -n "$w" ]] && candidates+=("$w")
  for fb in "${_COBALT_DOTNET_FALLBACKS[@]}"; do
    [[ -n "$fb" && -x "$fb" ]] && candidates+=("$fb")
  done
  for c in "${candidates[@]}"; do
    [[ " $seen " == *" $c "* ]] && continue
    seen="$seen $c"
    if _cobalt_dotnet_usable "$c"; then
      printf '%s' "$c"
      return 0
    fi
  done
  return 1
}

_cobalt_apply_dotnet_env() {
  local d
  d="$(cobalt_resolve_dotnet)" || {
    echo "cobalt: no working dotnet (install dotnet-sdk-8.0 or fix hostfxr)" >&2
    return 1
  }
  export COBALT_DOTNET="$d"
  export DOTNET_ROOT="$(cd "$(dirname "$d")" && pwd)"
  export PATH="$DOTNET_ROOT:${PATH:-}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  _cobalt_apply_dotnet_env || exit 127
  exec "$COBALT_DOTNET" "$@"
fi

_cobalt_apply_dotnet_env
