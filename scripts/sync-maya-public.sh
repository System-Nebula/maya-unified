#!/usr/bin/env bash
# Pull the latest canonical maya-public into this repo's maya-public/ subtree.
#
# maya-public development happens at https://github.com/System-Nebula/maya-public
# (branches + PRs there). This repo only *consumes* it — do not edit files under
# maya-public/ here; change them upstream and run this script.
set -euo pipefail

REMOTE="${MAYA_PUBLIC_REMOTE:-https://github.com/System-Nebula/maya-public.git}"
BRANCH="${MAYA_PUBLIC_BRANCH:-main}"

cd "$(git rev-parse --show-toplevel)"
git subtree pull --prefix maya-public "$REMOTE" "$BRANCH" --squash \
  -m "chore: sync maya-public subtree from $BRANCH"
echo "maya-public subtree synced from $REMOTE@$BRANCH"
