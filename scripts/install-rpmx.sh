#!/usr/bin/env bash
# Install the rpmx revision this repository is pinned to.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
revision=$(tr -d '[:space:]' <"$root/.rpmx-revision")

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo is required; install Rust 1.88 or newer first" >&2
  exit 1
fi

echo "Installing rpmx from rsturla/rpmx@${revision}"
exec cargo install \
  --git https://github.com/rsturla/rpmx \
  --rev "$revision" \
  --locked \
  "$@"
