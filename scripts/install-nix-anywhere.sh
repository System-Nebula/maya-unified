#!/usr/bin/env bash
# Install Nix on any Linux (Determinate installer) so `nix develop` works
# outside NixOS. Idempotent: no-op when nix is already on PATH.
# Safe to source or execute.
set -euo pipefail

source_nix_profile() {
  local f
  for f in \
    /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh \
    /nix/var/nix/profiles/default/etc/profile.d/nix.sh \
    "${HOME}/.nix-profile/etc/profile.d/nix.sh"; do
    if [[ -f "$f" ]]; then
      # shellcheck disable=SC1090
      . "$f"
    fi
  done
}

source_nix_profile

if command -v nix >/dev/null 2>&1; then
  echo "nix already installed: $(command -v nix)"
else
  if [[ "$(uname -s)" != "Linux" ]]; then
    echo "install-nix-anywhere.sh: Linux only (found $(uname -s))" >&2
    false
  fi
  echo "==> Installing Nix (Determinate, linux --init none)"
  curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix \
    | sh -s -- install linux --init none --no-confirm
  source_nix_profile
fi

if ! command -v nix >/dev/null 2>&1; then
  echo "nix is not on PATH after install-nix-anywhere.sh" >&2
  false
fi
