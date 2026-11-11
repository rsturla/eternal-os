#!/usr/bin/env bash
# Publish a built package set to S3-compatible object storage.
#
# The rolling repository is replaced on each run. The archive repository is
# append-only: current RPMs are copied into it, older objects are retained, and
# its repodata is merged from the current metadata plus the new build.
# Run only one publisher per destination bucket at a time, including manual runs.
#
# This script expects AWS CLI credentials in the environment. For Cloudflare
# R2, set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to an R2 access key and
# pass --endpoint-url https://<account>.r2.cloudflarestorage.com.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

packages=out
output=site
release=rolling
archive=archive
bucket=
endpoint=
region=${AWS_DEFAULT_REGION:-auto}
base_url=
signing_key=
public_key=

usage() {
  cat <<'EOF'
usage: publish-bucket.sh --packages DIR --bucket NAME --base-url URL [options]

  --packages DIR       Current artifacts root produced by build-all.sh
  --output DIR         Local repository tree to write (default: site)
  --release VER        Current release directory (default: rolling)
  --archive VER        Historical release directory (default: archive)
  --bucket NAME        Destination bucket, with or without the s3:// prefix
  --endpoint-url URL   S3-compatible endpoint (for example Cloudflare R2)
  --region REGION      AWS region (default: AWS_DEFAULT_REGION or auto)
  --base-url URL       Consumer-facing repository base URL
  --signing-key FILE   Sign repodata with this OpenPGP secret key
  --public-key FILE    Publish this public key as RPM-GPG-KEY-eternal
  -h, --help           Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --packages)
      packages=${2:?--packages needs a directory}
      shift 2
      ;;
    --output)
      output=${2:?--output needs a directory}
      shift 2
      ;;
    --release)
      release=${2:?--release needs a version}
      shift 2
      ;;
    --archive)
      archive=${2:?--archive needs a version}
      shift 2
      ;;
    --bucket)
      bucket=${2:?--bucket needs a name}
      shift 2
      ;;
    --endpoint-url)
      endpoint=${2:?--endpoint-url needs a URL}
      shift 2
      ;;
    --region)
      region=${2:?--region needs a value}
      shift 2
      ;;
    --base-url)
      base_url=${2:?--base-url needs a URL}
      shift 2
      ;;
    --signing-key)
      signing_key=${2:?--signing-key needs a file}
      shift 2
      ;;
    --public-key)
      public_key=${2:?--public-key needs a file}
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n $bucket ]] || {
  echo "--bucket is required" >&2
  exit 2
}
[[ -n $base_url ]] || {
  echo "--base-url is required" >&2
  exit 2
}
[[ -d $packages ]] || {
  echo "artifacts directory not found: $packages" >&2
  exit 1
}
command -v aws >/dev/null || {
  echo "the AWS CLI is required to publish the repository" >&2
  exit 127
}
for tool in mergerepo_c modifyrepo_c python3 jq; do
  command -v "$tool" >/dev/null || {
    echo "$tool is required to publish the archive" >&2
    exit 127
  }
done
if [[ -n $signing_key ]]; then
  command -v gpg >/dev/null || {
    echo "gpg is required to sign the archive metadata" >&2
    exit 127
  }
fi

bucket=${bucket#s3://}
bucket=${bucket%/}
bucket_uri="s3://$bucket"
export AWS_DEFAULT_REGION=$region
# R2 does not implement the CRC64NVME trailing checksum that recent AWS CLI
# releases add by default. Let the service use its normal integrity checks.
export AWS_REQUEST_CHECKSUM_CALCULATION=${AWS_REQUEST_CHECKSUM_CALCULATION:-when_required}
export AWS_RESPONSE_CHECKSUM_VALIDATION=${AWS_RESPONSE_CHECKSUM_VALIDATION:-when_required}

aws_cmd=(aws)
[[ -n $endpoint ]] && aws_cmd+=(--endpoint-url "$endpoint")

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mapfile -t arches < <("$root/scripts/list-arches.sh" | jq -r '.[]')

# Fetch only the current snapshot. Retained snapshots and RPMs stay in S3.
# Listing errors must fail the run, rather than look like an empty repository.
archive_metadata="$work/archive"
mkdir -p "$archive_metadata"
for arch in "${arches[@]}" SRPMS; do
  prefix="$archive/$arch/"
  objects=$("${aws_cmd[@]}" s3api list-objects-v2 --bucket "$bucket" \
    --prefix "$prefix" --max-keys 1 --no-paginate)
  if [[ $(jq '.Contents | length' <<<"$objects") == 0 ]]; then
    continue
  fi
  dest="$archive_metadata/$arch"
  mkdir -p "$dest/repodata"
  echo "==> fetch $archive/$arch metadata"
  # An existing prefix without an index is an error, not a first publication.
  "${aws_cmd[@]}" s3 cp "$bucket_uri/${prefix}repodata/repomd.xml" \
    "$dest/repodata/repomd.xml" --only-show-errors
  python3 "$root/scripts/repodata-files.py" "$dest/repodata/repomd.xml" >"$work/metadata-files"
  while IFS= read -r href; do
    "${aws_cmd[@]}" s3 cp "$bucket_uri/$prefix$href" "$dest/$href" --only-show-errors
  done <"$work/metadata-files"
  signature="${prefix}repodata/repomd.xml.asc"
  objects=$("${aws_cmd[@]}" s3api list-objects-v2 --bucket "$bucket" \
    --prefix "$signature" --max-keys 1 --no-paginate)
  if jq -e --arg key "$signature" 'any(.Contents[]?; .Key == $key)' <<<"$objects" >/dev/null; then
    "${aws_cmd[@]}" s3 cp "$bucket_uri/$signature" "$dest/repodata/repomd.xml.asc" --only-show-errors
  fi
done

repo_args=(
  --packages "$packages"
  --archive-metadata "$archive_metadata"
  --output "$output"
  --release "$release"
  --archive-release "$archive"
  --base-url "$base_url"
)
[[ -n $signing_key ]] && repo_args+=(--signing-key "$signing_key")
[[ -n $public_key ]] && repo_args+=(--public-key "$public_key")

"$root/scripts/publish-repo.sh" "${repo_args[@]}"

upload_file() {
  local source=$1 destination=$2 cache_control=$3
  "${aws_cmd[@]}" s3 cp "$source" "$bucket_uri/$destination" \
    --cache-control "$cache_control" --only-show-errors
}

sync_immutable() {
  local source=$1 destination=$2
  "${aws_cmd[@]}" s3 sync "$source" "$destination" \
    --exclude 'repodata/*' \
    --cache-control 'public, max-age=31536000, immutable' \
    --only-show-errors
}

sync_repodata() {
  local source=$1 destination=$2
  # Keep metadata referenced by an index a client may already have read.
  # Upload the immutable data before switching the index to the new snapshot.
  "${aws_cmd[@]}" s3 sync "$source" "$destination" \
    --exclude 'repomd.xml' --exclude 'repomd.xml.asc' \
    --cache-control 'public, max-age=31536000, immutable' \
    --only-show-errors
  if [[ -f "$source/repomd.xml.asc" ]]; then
    "${aws_cmd[@]}" s3 cp "$source/repomd.xml.asc" "$destination/repomd.xml.asc" \
      --cache-control 'no-cache' --only-show-errors
  fi
  "${aws_cmd[@]}" s3 cp "$source/repomd.xml" "$destination/repomd.xml" \
    --cache-control 'no-cache' --only-show-errors
}

# Root metadata is small and changes every release.
upload_file "$output/index.html" index.html 'no-cache'
upload_file "$output/eternal.repo" eternal.repo 'no-cache'
upload_file "$output/.nojekyll" .nojekyll 'no-cache'
if [[ -f "$output/RPM-GPG-KEY-eternal" ]]; then
  upload_file "$output/RPM-GPG-KEY-eternal" RPM-GPG-KEY-eternal \
    'public, max-age=31536000, immutable'
fi

# Rolling RPMs are immutable objects. Do not delete old ones: a CI run that
# resolved a root before this publish may still fetch the exact old URL.
for arch in "${arches[@]}"; do
  if [[ -d "$output/$release/$arch" ]]; then
    sync_immutable "$output/$release/$arch" "$bucket_uri/$release/$arch"
  fi
  if [[ -d "$output/$release/$arch/repodata" ]]; then
    sync_repodata "$output/$release/$arch/repodata" \
      "$bucket_uri/$release/$arch/repodata"
  fi
done
if [[ -d "$output/$release/SRPMS" ]]; then
  sync_immutable "$output/$release/SRPMS" "$bucket_uri/$release/SRPMS"
  if [[ -d "$output/$release/SRPMS/repodata" ]]; then
    sync_repodata "$output/$release/SRPMS/repodata" \
      "$bucket_uri/$release/SRPMS/repodata"
  fi
fi

# The archive is append-only. Upload only this run's RPMs; historical objects
# are already in the bucket, and only the archive repodata is replaced.
for arch in "${arches[@]}"; do
  if [[ -d "$output/$release/$arch" ]]; then
    sync_immutable "$output/$release/$arch" "$bucket_uri/$archive/$arch"
  fi
  if [[ -d "$output/$archive/$arch/repodata" ]]; then
    sync_repodata "$output/$archive/$arch/repodata" \
      "$bucket_uri/$archive/$arch/repodata"
  fi
done
if [[ -d "$output/$release/SRPMS" ]]; then
  sync_immutable "$output/$release/SRPMS" "$bucket_uri/$archive/SRPMS"
fi
if [[ -d "$output/$archive/SRPMS/repodata" ]]; then
  sync_repodata "$output/$archive/SRPMS/repodata" \
    "$bucket_uri/$archive/SRPMS/repodata"
fi

echo "published $release and $archive to $bucket_uri"
