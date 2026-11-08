#!/usr/bin/env bash
# Assemble the published repository tree from built artifacts.
#
# Inputs may be flat (out/<arch>/*.rpm, as in a single-package CI job) or
# per-package (out/<package>/<arch>/*.rpm, as in a local full build). RPMs are
# gathered by architecture into a staging directory before repodata is written,
# so a test or build never sees unrelated packages.
#
# The rolling repository is the enabled channel. An optional archive repository
# holds every historical EVR and is disabled by default; DNF can enable it when
# a user needs to pin or downgrade to an older release.
#
# Layout:
#   OUTPUT/
#     .nojekyll
#     index.html
#     eternal.repo
#     RPM-GPG-KEY-eternal        (when --public-key is given)
#     RELEASE/<arch>/            RPMs + repodata
#     RELEASE/SRPMS/             source RPMs + repodata
#     ARCHIVE/<arch>/            historical RPMs + repodata (when requested)
#     ARCHIVE/SRPMS/             historical source RPMs + repodata
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}

packages=
archive_packages=
output=site
release=rolling
archive_release=
signing_key=
public_key=
base_url=https://packages.eternal.sturla.tech

usage() {
  cat <<'EOF'
usage: publish-repo.sh --packages DIR [options]

  --packages DIR           Current artifacts root produced by build-all.sh
  --archive-packages DIR   Historical artifacts root; adds the archive repository
  --output DIR             Repository mirror to write (default: site)
  --release VER            Current release directory (default: rolling)
  --archive-release VER    Historical release directory (default: archive)
  --signing-key FILE       Sign repodata with this OpenPGP secret key
  --public-key FILE        Copy this public key to RPM-GPG-KEY-eternal
  --base-url URL           Consumer-facing repository base URL
  -h, --help               Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --packages)
      packages=${2:?--packages needs a directory}
      shift 2
      ;;
    --archive-packages)
      archive_packages=${2:?--archive-packages needs a directory}
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
    --archive-release)
      archive_release=${2:?--archive-release needs a version}
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
    --base-url)
      base_url=${2:?--base-url needs a URL}
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

[[ -n $packages ]] || {
  echo "--packages is required" >&2
  exit 2
}
[[ -d $packages ]] || {
  echo "artifacts directory not found: $packages" >&2
  exit 1
}
if [[ -n $archive_release && -z $archive_packages ]]; then
  echo "--archive-release needs --archive-packages" >&2
  exit 2
fi
if [[ -n $archive_packages && -z $archive_release ]]; then
  echo "--archive-packages needs --archive-release" >&2
  exit 2
fi
if [[ -n $archive_packages && ! -d $archive_packages ]]; then
  echo "archive artifacts directory not found: $archive_packages" >&2
  exit 1
fi

stage_root=$(mktemp -d)
trap 'rm -rf "$stage_root"' EXIT
mkdir -p "$output"

assemble_repo() {
  local packages_root=$1 repo_release=$2
  local stage="$stage_root/$repo_release"
  local source_stage="$stage/SRPMS"
  local found=0 source_found=0
  local rpm arch
  local -A seen=()
  local -a cmd

  mkdir -p "$stage"

  # Group every binary RPM by its parent directory's name (the architecture).
  # Depth 2 covers out/<arch>/*.rpm; depth 3 covers out/<package>/<arch>/*.rpm.
  # Source RPMs live one level deeper under src/; they are collected separately
  # below and published under <release>/SRPMS.
  while IFS= read -r -d '' rpm; do
    arch=$(basename "$(dirname "$rpm")")
    [[ $arch == src ]] && continue
    mkdir -p "$stage/$arch"
    cp -f "$rpm" "$stage/$arch/"
    seen[$arch]=1
    found=$((found + 1))
  done < <(find "$packages_root" -mindepth 2 -maxdepth 3 -type f -name '*.rpm' ! -name '*.src.rpm' -print0)

  if ((found == 0)); then
    echo "no binary RPMs found under $packages_root" >&2
    exit 1
  fi

  # Source RPMs are architecture-independent, so the same filename from two
  # arches collapses to one copy in the source repository.
  while IFS= read -r -d '' rpm; do
    mkdir -p "$source_stage"
    cp -f "$rpm" "$source_stage/"
    source_found=$((source_found + 1))
  done < <(find "$packages_root" -type f -name '*.src.rpm' -print0)

  for arch in "${!seen[@]}"; do
    local dest="$output/$repo_release/$arch"
    rm -rf "$dest"
    mkdir -p "$dest"

    cmd=("$rpmx" repo --rpms "$stage/$arch" --output "$dest")
    [[ -n $signing_key ]] && cmd+=(--signing-key "$signing_key")
    echo "==> repo $repo_release/$arch -> ${dest#"$root"/}"
    "${cmd[@]}"
  done

  if ((source_found > 0)); then
    local dest="$output/$repo_release/SRPMS"
    rm -rf "$dest"
    mkdir -p "$dest"
    cmd=("$rpmx" repo --rpms "$source_stage" --output "$dest")
    [[ -n $signing_key ]] && cmd+=(--signing-key "$signing_key")
    echo "==> repo $repo_release/SRPMS -> ${dest#"$root"/}"
    "${cmd[@]}"
  fi
}

assemble_repo "$packages" "$release"
if [[ -n $archive_release ]]; then
  assemble_repo "$archive_packages" "$archive_release"
fi

# Keep the marker so a local mirror can also be served by GitHub Pages or any
# other static host.
touch "$output/.nojekyll"

cat >"$output/index.html" <<'HTML'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Eternal Linux packages</title>
  </head>
  <body>
    <h1>Eternal Linux packages</h1>
    <p>
      Configure dnf with the <code>eternal.repo</code> file published beside
      this page. Release directories are laid out as
      <code>&lt;releasever&gt;/&lt;basearch&gt;</code>; source packages live
      under <code>&lt;releasever&gt;/SRPMS</code>.
    </p>
    <ul>
      <li><a href="eternal.repo">eternal.repo</a></li>
      <li><a href="RPM-GPG-KEY-eternal">RPM-GPG-KEY-eternal</a></li>
      <li><a href="__RELEASE__/SRPMS/">__RELEASE__/SRPMS</a></li>
      <li><a href="__ARCHIVE__/SRPMS/">__ARCHIVE__/SRPMS</a></li>
    </ul>
  </body>
</html>
HTML

if [[ ! -d "$output/$release/SRPMS/repodata" ]]; then
  sed -i '\|__RELEASE__/SRPMS|d' "$output/index.html"
fi
if [[ -z $archive_release || ! -d "$output/$archive_release/SRPMS/repodata" ]]; then
  sed -i '\|__ARCHIVE__/SRPMS|d' "$output/index.html"
fi
sed -i "s|__RELEASE__|$release|g" "$output/index.html"
if [[ -n $archive_release ]]; then
  sed -i "s|__ARCHIVE__|$archive_release|g" "$output/index.html"
fi

gpgcheck=0
if [[ -n $public_key ]]; then
  install -m 0644 "$public_key" "$output/RPM-GPG-KEY-eternal"
  gpgcheck=1
fi

cat >"$output/eternal.repo" <<EOF
[eternal]
name=Eternal Linux \$releasever - \$basearch
baseurl=${base_url}/\$releasever/\$basearch
enabled=1
gpgcheck=${gpgcheck}
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-eternal
metadata_expire=6h
countme=0
EOF

if [[ -d "$output/$release/SRPMS/repodata" ]]; then
  cat >>"$output/eternal.repo" <<EOF

[eternal-source]
name=Eternal Linux \$releasever - Source
baseurl=${base_url}/\$releasever/SRPMS
enabled=0
gpgcheck=${gpgcheck}
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-eternal
metadata_expire=6h
countme=0
EOF
fi

if [[ -n $archive_release ]]; then
  cat >>"$output/eternal.repo" <<EOF

[eternal-archive]
name=Eternal Linux \$releasever - \$basearch - Archive
baseurl=${base_url}/${archive_release}/\$basearch
enabled=0
gpgcheck=${gpgcheck}
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-eternal
metadata_expire=7d
countme=0
EOF

  if [[ -d "$output/$archive_release/SRPMS/repodata" ]]; then
    cat >>"$output/eternal.repo" <<EOF

[eternal-archive-source]
name=Eternal Linux \$releasever - Source - Archive
baseurl=${base_url}/${archive_release}/SRPMS
enabled=0
gpgcheck=${gpgcheck}
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-eternal
metadata_expire=7d
countme=0
EOF
  fi
fi

echo "repository written to ${output#"$root"/}/$release"
