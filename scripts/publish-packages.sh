#!/usr/bin/env bash
# Sign tested RPM envelopes, then publish packages and repository metadata.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
[[ $# == 1 ]] || { echo 'usage: publish-packages.sh PACKAGES' >&2; exit 2; }
output=$1
args=(--incremental --packages "$output" --output "$output/site"
  --bucket "${PACKAGES_S3_BUCKET:?}" --base-url "${PACKAGES_BASE_URL:?}"
  --region "${AWS_DEFAULT_REGION:-auto}")
[[ -z ${PACKAGES_S3_ENDPOINT:-} ]] || args+=(--endpoint-url "$PACKAGES_S3_ENDPOINT")
keys=$(mktemp -d)
trap 'rm -rf "$keys"' EXIT
if [[ -n ${RPMX_SIGNING_KEY:-} ]]; then
  printf '%s' "$RPMX_SIGNING_KEY" >"$keys/signing.asc"
  chmod 0600 "$keys/signing.asc"
  python3 "$root/scripts/sign-packages.py" "$output" --signing-key "$keys/signing.asc"
  args+=(--signing-key "$keys/signing.asc")
fi
if [[ -n ${RPMX_PUBLIC_KEY:-} ]]; then
  printf '%s' "$RPMX_PUBLIC_KEY" >"$keys/public.asc"
  args+=(--public-key "$keys/public.asc")
fi
"$root/scripts/publish-bucket.sh" "${args[@]}"
