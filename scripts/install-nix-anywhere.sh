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

ensure_nix_daemon() {
  local sock="/nix/var/nix/daemon-socket/socket"
  local daemon_bin=""
  local candidate
  for candidate in \
    /nix/var/nix/profiles/default/bin/nix-daemon \
    /root/.nix-profile/bin/nix-daemon; do
    if [[ -x "$candidate" ]]; then
      daemon_bin="$candidate"
      break
    fi
  done
  if [[ -z "$daemon_bin" ]] && command -v nix-daemon >/dev/null 2>&1; then
    daemon_bin="$(command -v nix-daemon)"
  fi
  if [[ -z "$daemon_bin" ]]; then
    return 0
  fi
  if [[ -S "$sock" ]]; then
    return 0
  fi
  echo "==> starting nix-daemon (no systemd init)"
  if command -v sudo >/dev/null 2>&1; then
    sudo mkdir -p "$(dirname "$sock")"
    sudo nohup "$daemon_bin" >/tmp/nix-daemon.log 2>&1 &
  else
    mkdir -p "$(dirname "$sock")"
    nohup "$daemon_bin" >/tmp/nix-daemon.log 2>&1 &
  fi
  local i
  for i in $(seq 1 30); do
    if [[ -S "$sock" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "nix-daemon socket did not appear at $sock" >&2
  false
}

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

ensure_nix_daemon

if ! command -v nix >/dev/null 2>&1; then
  echo "nix is not on PATH after install-nix-anywhere.sh" >&2
  false
fi
