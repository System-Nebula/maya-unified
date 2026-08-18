#!/usr/bin/env bash
# Give uv manylinux wheels a Nix-compatible loader path.
#
# `.venv/bin/python` is often the nixpkgs interpreter. Its dynamic linker does
# not search FHS `/usr/lib/*/libstdc++.so.6`, so greenlet/SQLAlchemy fail with
# "libstdc++.so.6: cannot open shared object file" outside `nix develop`.
# Stamp the flake's `makeLibraryPath` onto the venv and add it as RPATH.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$ROOT/.venv/nix-ld-library-path"

stamp() {
  local path="${LD_LIBRARY_PATH:-}"
  if [[ -z "$path" ]]; then
    return 1
  fi
  mkdir -p "$ROOT/.venv"
  printf '%s\n' "$path" > "$STAMP"
}

library_path() {
  if [[ -f "$STAMP" ]]; then
    tr -d '\n' < "$STAMP"
    return 0
  fi
  if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
    printf '%s' "$LD_LIBRARY_PATH"
    return 0
  fi
  return 1
}

export_libs() {
  local extra
  extra="$(library_path)" || return 0
  export LD_LIBRARY_PATH="${extra}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}

_has_rpath_dir() {
  local so="$1"
  local dir="$2"
  local current
  current="$(patchelf --print-rpath "$so" 2>/dev/null || true)"
  [[ ":${current}:" == *":${dir}:"* ]]
}

patch_venv() {
  stamp || true
  local extra
  extra="$(library_path)" || return 0
  if ! command -v patchelf >/dev/null 2>&1; then
    return 0
  fi
  local so dir
  while IFS= read -r -d '' so; do
    if ! patchelf --print-needed "$so" 2>/dev/null | grep -Eq 'libstdc\+\+|libgcc_s|libz\.so|libportaudio|libssl|libffi'; then
      continue
    fi
    IFS=':' read -ra dirs <<< "$extra"
    for dir in "${dirs[@]}"; do
      [[ -n "$dir" && -d "$dir" ]] || continue
      if _has_rpath_dir "$so" "$dir"; then
        continue
      fi
      patchelf --add-rpath "$dir" "$so" 2>/dev/null || true
    done
  done < <(find "$ROOT/.venv" -type f -name '*.so' -print0 2>/dev/null)
}

usage() {
  echo "usage: $0 [stamp|patch|export]" >&2
  exit 2
}

case "${1:-export}" in
  stamp) stamp ;;
  patch) patch_venv ;;
  export)
    export_libs
    echo "export LD_LIBRARY_PATH=$(printf '%q' "${LD_LIBRARY_PATH:-}")"
    ;;
  *) usage ;;
esac
