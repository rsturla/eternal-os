#!/usr/bin/env bash
# Assemble the published repository tree from built artifacts.
#
# Inputs may be flat (out/<arch>/*.rpm, as in a single-package CI job) or
# per-package (out/<package>/<arch>/*.rpm, as in a local full build).
# Source RPMs must be under the corresponding <arch>/src/ directory.
# RPMs are gathered by architecture before repodata is written,
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
#     ARCHIVE/<arch>/            metadata, plus RPMs with --archive-packages
#     ARCHIVE/SRPMS/             source metadata, plus RPMs with --archive-packages
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
rpmx=${RPMX:-rpmx}

packages=
archive_packages=
archive_metadata=
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
  --archive-metadata DIR   Previous <arch>/repodata trees; merge with current RPMs
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
    --archive-metadata)
      archive_metadata=${2:?--archive-metadata needs a directory}
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
if [[ -n $archive_packages && -n $archive_metadata ]]; then
  echo "--archive-packages and --archive-metadata are mutually exclusive" >&2
  exit 2
fi
if [[ -n $archive_release && -z $archive_packages && -z $archive_metadata ]]; then
  echo "--archive-release needs --archive-packages or --archive-metadata" >&2
  exit 2
fi
if [[ ( -n $archive_packages || -n $archive_metadata ) && -z $archive_release ]]; then
  echo "archive inputs need --archive-release" >&2
  exit 2
fi
if [[ -n $archive_metadata && ! -d $archive_metadata ]]; then
  echo "archive metadata directory not found: $archive_metadata" >&2
  exit 1
fi
if [[ ! $release =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ||
  ( -n $archive_release && ! $archive_release =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ) ||
  $release == "$archive_release" ]]; then
  echo "release names must be distinct directory names" >&2
  exit 2
fi
if [[ -n $archive_packages && ! -d $archive_packages ]]; then
  echo "archive artifacts directory not found: $archive_packages" >&2
  exit 1
fi
if [[ -n $archive_metadata ]]; then
  metadata_input=$(realpath "$archive_metadata")
  for channel in "$release" "$archive_release"; do
    destination=$(realpath -m "$output/$channel")
    if [[ $metadata_input == "$destination" || $metadata_input == "$destination/"* ||
      $destination == "$metadata_input/"* ]]; then
      echo "--archive-metadata must not overlap the output repositories" >&2
      exit 2
    fi
  done
fi

stage_root=$(mktemp -d)
trap 'rm -rf "$stage_root"' EXIT
mkdir -p "$output"

merge_archive() {
  local repo arch dest previous signature kind href
  local signing_home="$stage_root/gnupg"
  local -A seen=()
  local -a cmd

  if [[ -n $signing_key ]]; then
    install -d -m 0700 "$signing_home"
    gpg --homedir "$signing_home" --batch --import "$signing_key"
    if [[ -n $public_key ]]; then
      gpg --homedir "$signing_home" --batch --import "$public_key"
    fi
  fi
  rm -rf "${output:?}/${archive_release:?}"
  for repo in "$archive_metadata"/* "$output/$release"/*; do
    [[ -d $repo ]] || continue
    arch=$(basename "$repo")
    [[ -z ${seen[$arch]:-} ]] || continue
    seen[$arch]=1
    dest="$output/$archive_release/$arch"
    previous="$archive_metadata/$arch"
    cmd=(mergerepo_c --all --omit-baseurl --no-database --unique-md-filenames --nogroups --noupdateinfo
      --compress-type=gz --outputdir "$dest")
    if [[ -d "$previous" ]]; then
      python3 "$root/scripts/repodata-files.py" --verify "$previous/repodata/repomd.xml"
      signature="$previous/repodata/repomd.xml.asc"
      if [[ -f $signature ]]; then
        if [[ -z $signing_key ]]; then
          echo "cannot update a signed archive without --signing-key" >&2
          exit 1
        fi
        gpg --homedir "$signing_home" --batch --verify "$signature" "$previous/repodata/repomd.xml"
      fi
      # Keep the historical record if an immutable NEVRA occurs in both inputs.
      cmd+=(--repo "$(realpath "$previous")")
    fi
    if [[ -f "$output/$release/$arch/repodata/repomd.xml" ]]; then
      cmd+=(--repo "$(realpath "$output/$release/$arch")")
    fi
    echo "==> merge $archive_release/$arch metadata"
    "${cmd[@]}"
    if [[ -d "$previous" ]]; then
      # mergerepo_c writes an empty updateinfo file. Retain the archive's
      # policy records separately; rpmx supplies only package metadata.
      python3 "$root/scripts/repodata-files.py" --additional "$previous/repodata/repomd.xml" \
        >"$stage_root/additional-metadata"
      while IFS=$'\t' read -r kind href; do
        modifyrepo_c --mdtype "$kind" --new-name "$kind.xml.gz" \
          --compress --compress-type=gz --unique-md-filenames \
          "$previous/$href" "$dest/repodata"
      done <"$stage_root/additional-metadata"
    fi
    if [[ -n $signing_key ]]; then
      gpg --homedir "$signing_home" --batch --yes --pinentry-mode error \
        --armor --detach-sign --output "$dest/repodata/repomd.xml.asc" \
        "$dest/repodata/repomd.xml"
    fi
  done
}

assemble_repo() {
  local packages_root repo_release=$2
  packages_root=$(realpath -e -- "$1")
  local stage="$stage_root/$repo_release"
  local source_stage="$stage/SRPMS"
  local found=0 source_found=0
  local rpm arch relative arch_document
  local -A seen=() valid_arches=()
  local -a parts cmd
  arch_document=$("$root/scripts/list-arches.sh")
  while IFS= read -r arch; do valid_arches[$arch]=1; done < <(jq -r '.[]' <<<"$arch_document")

  mkdir -p "$stage"

  # Accept only the two documented layouts and configured target architectures.
  # Reports and quarantined producers can contain executable RPM fixtures.
  # Depth 2 covers out/<arch>/*.rpm; depth 3 covers out/<package>/<arch>/*.rpm.
  # Source RPMs live one level deeper under src/; they are collected separately
  # below and published under <release>/SRPMS.
  while IFS= read -r -d '' rpm; do
    relative=${rpm#"$packages_root"/}
    IFS=/ read -r -a parts <<<"$relative"
    case ${parts[0]} in evidence|test-reports|producers|producer-*|compiler-producers) continue ;; esac
    case ${#parts[@]} in
      2) arch=${parts[0]} ;;
      3) arch=${parts[1]} ;;
      *) continue ;;
    esac
    [[ ${valid_arches[$arch]-} == 1 ]] || continue
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
    relative=${rpm#"$packages_root"/}
    IFS=/ read -r -a parts <<<"$relative"
    case ${parts[0]} in evidence|test-reports|producers|producer-*|compiler-producers) continue ;; esac
    case ${#parts[@]} in
      3) arch=${parts[0]}; [[ ${parts[1]} == src ]] || continue ;;
      4) arch=${parts[1]}; [[ ${parts[2]} == src ]] || continue ;;
      *) continue ;;
    esac
    [[ ${valid_arches[$arch]-} == 1 ]] || continue
    mkdir -p "$source_stage"
    cp -f "$rpm" "$source_stage/"
    source_found=$((source_found + 1))
  done < <(find "$packages_root" -mindepth 3 -maxdepth 4 -type f -name '*.src.rpm' -print0)

  rm -rf "${output:?}/${repo_release:?}"
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
if [[ -n $archive_metadata ]]; then
  merge_archive
elif [[ -n $archive_release ]]; then
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
