#!/usr/bin/env bash
# Compose the base image from the published package repository.
#
# This is the apko half of the Wolfi model: install a package set into a fresh
# root, import that root as an OCI image, tag it and (optionally) push it.
# Nothing is layered on top of another distribution's base image.
set -euo pipefail

repo=
releasever=44
image_version=rolling
arch=x86_64
packages=
work=
push=0
tags=()

usage() {
  cat <<'EOF'
usage: build-image.sh --repo DIR --tag REF [options]

  --repo DIR         Repository directory containing the RPMs and repodata
  --tag REF          Image reference (repeatable)
  --packages LIST    Space-separated package set (default: eternal-base)
  --releasever VER   dnf releasever used during composition (default: 44)
  --image-version V  OCI version label (default: rolling)
  --arch ARCH        Architecture of the repository (default: x86_64)
  --work DIR         Keep the rootfs under DIR instead of a temporary directory
  --push             Push every tag after building
  -h, --help         Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --repo)
      repo=${2:?--repo needs a directory}
      shift 2
      ;;
    --tag)
      tags+=("${2:?--tag needs a reference}")
      shift 2
      ;;
    --packages)
      packages=${2:?--packages needs a list}
      shift 2
      ;;
    --releasever)
      releasever=${2:?--releasever needs a version}
      shift 2
      ;;
    --image-version)
      image_version=${2:?--image-version needs a value}
      shift 2
      ;;
    --arch)
      arch=${2:?--arch needs an architecture}
      shift 2
      ;;
    --work)
      work=${2:?--work needs a directory}
      shift 2
      ;;
    --push)
      push=1
      shift
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

[[ -n $repo ]] || {
  echo "--repo is required" >&2
  exit 2
}
((${#tags[@]} > 0)) || {
  echo "at least one --tag is required" >&2
  exit 2
}
[[ -d $repo ]] || {
  echo "repository directory not found: $repo" >&2
  exit 1
}
command -v podman >/dev/null 2>&1 || {
  echo "podman is required to compose the image" >&2
  exit 1
}

repo=$(realpath "$repo")
if [[ -z $packages ]]; then
  packages=eternal-base
fi
cleanup=
if [[ -z $work ]]; then
  work=$(mktemp -d)
  cleanup=$work
fi
rootfs="$work/rootfs"
if [[ -e $rootfs ]]; then
  podman unshare rm -rf "$rootfs"
fi
mkdir -p "$rootfs"

# dnf resolves packages inside a bootstrap container but installs them into the
# fresh root. The Eternal repository is mounted read-only and added with
# --repofrompath; the bootstrap repositories the base set still needs come from
# the container image itself.
echo "==> compose $packages for $arch (releasever $releasever)"
podman run --rm --privileged --network=host --security-opt label=disable \
  -v "$repo:/run/eternal-repo:ro" \
  -v "$work:/work" \
  "registry.fedoraproject.org/fedora:$releasever" \
  bash -euxo pipefail -c "
    dnf5 -y --installroot=/work/rootfs --releasever=$releasever \
      --use-host-config \
      --setopt=install_weak_deps=False \
      --setopt=tsflags=nodocs \
      --setopt=keepcache=False \
      --repofrompath=eternal,/run/eternal-repo \
      --setopt=eternal.gpgcheck=0 \
      --setopt=eternal.repo_gpgcheck=0 \
      install --allowerasing $packages
    dnf5 -y --installroot=/work/rootfs clean all
    rm -rf /work/rootfs/var/cache/dnf /work/rootfs/var/cache/libdnf5 \
           /work/rootfs/var/log/dnf5.log /work/rootfs/var/log/dnf.log
  "

# Files a container needs that a package set does not create on its own.
install -d -m 1777 "$rootfs/tmp" "$rootfs/var/tmp"
install -d -m 0755 "$rootfs/run" "$rootfs/root"
if [[ ! -e $rootfs/etc/hostname ]]; then
  printf 'eternal\n' >"$rootfs/etc/hostname"
fi

echo "==> import ${tags[0]}"
# tar must run in the rootless user namespace: /etc/shadow is mode 000, and the
# namespace makes the invoking user root for the read while preserving the
# container-relative numeric ownership that import expects.
podman unshare tar --numeric-owner --acls --xattrs -C "$rootfs" -cf - . |
  podman import \
    --change 'ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
    --change 'CMD ["/bin/bash"]' \
    --change 'LABEL org.opencontainers.image.title=Eternal Linux base' \
    --change 'LABEL org.opencontainers.image.description=The Eternal Linux base system' \
    --change 'LABEL org.opencontainers.image.source=https://github.com/rsturla/eternal-os' \
    --change 'LABEL org.opencontainers.image.licenses=MIT' \
    --change "LABEL org.opencontainers.image.version=$image_version" \
    - "${tags[0]}"

for tag in "${tags[@]:1}"; do
  podman tag "${tags[0]}" "$tag"
done

if ((push)); then
  for tag in "${tags[@]}"; do
    echo "==> push $tag"
    podman push "$tag"
  done
fi

if [[ -n $cleanup ]]; then
  podman unshare rm -rf "$cleanup"
fi
