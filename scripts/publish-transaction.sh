#!/usr/bin/env bash
# Publish exactly the source and binary bytes accepted by this transaction.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ $# == 3 ]] || { echo 'usage: publish-transaction.sh STATE ARTIFACTS OUTPUT' >&2; exit 2; }
state=$1 artifacts=$2 output=$3
python3 "$root/scripts/transaction-artifacts.py" stage --state "$state" --artifacts "$artifacts" --output "$output"
args=(--incremental --packages "$output" --output "$output/site"
  --bucket "${PACKAGES_S3_BUCKET:?}" --base-url "${PACKAGES_BASE_URL:?}"
  --region "${AWS_DEFAULT_REGION:-auto}")
[[ -z ${PACKAGES_S3_ENDPOINT:-} ]] || args+=(--endpoint-url "$PACKAGES_S3_ENDPOINT")
keys=$(mktemp -d)
trap 'rm -rf "$keys"' EXIT
if [[ -n ${RPMX_SIGNING_KEY:-} ]]; then
  printf '%s' "$RPMX_SIGNING_KEY" >"$keys/signing.asc"
  chmod 0600 "$keys/signing.asc"
  args+=(--signing-key "$keys/signing.asc")
fi
if [[ -n ${RPMX_PUBLIC_KEY:-} ]]; then
  printf '%s' "$RPMX_PUBLIC_KEY" >"$keys/public.asc"
  args+=(--public-key "$keys/public.asc")
fi
"$root/scripts/publish-bucket.sh" "${args[@]}"
