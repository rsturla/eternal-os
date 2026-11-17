#!/usr/bin/env bash
# Publish exactly the source and binary bytes accepted by this transaction.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ $# == 3 ]] || { echo 'usage: publish-transaction.sh STATE ARTIFACTS OUTPUT' >&2; exit 2; }
state=$1 artifacts=$2 output=$3
python3 "$root/scripts/transaction-artifacts.py" stage --state "$state" --artifacts "$artifacts" --output "$output"
exec "$root/scripts/publish-packages.sh" "$output"
