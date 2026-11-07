# Base image

The Eternal base image is a package set, not a Dockerfile. `scripts/build-image.sh`
composes it from the published repository:

```text
repository RPMs
      |
      v
dnf5 --installroot  ->  rootfs/  ->  podman import  ->  ghcr.io/rsturla/eternal-os/base:rolling
```

## What is in it

The package list is `packages/eternal-base/package.yaml`:

- `eternal-release` — `/etc/os-release` and the Eternal repository;
- `eternal-baselayout` — Eternal-specific directories;
- `basesystem`, `bash`, `coreutils`, `dnf5`, `ca-certificates`, `tzdata`,
  `util-linux`, `shadow-utils`.

The last group is still provided by the bootstrap repositories. When a package
gains an in-tree recipe with the same name, no change is needed here.

## Build locally

```console
make repo
make image
podman run --rm -it ghcr.io/rsturla/eternal-os/base:rolling
```

Check the identity:

```console
podman run --rm ghcr.io/rsturla/eternal-os/base:rolling \
  sh -c '. /etc/os-release && echo "$PRETTY_NAME"'
```

## Publish

`release.yml` publishes the package repository but does **not** build images.
Image composition is a separate pipeline: it should consume the repository
published for the same run and push `:rolling`, `:latest` and
`:sha-<commit>` manifest lists for x86_64 and aarch64. The image is never built
from a branch checkout; it only contains packages that were published.

## Design notes

- The image has no extra layers and no bootstrap base image. The root filesystem
  is the package set.
- `dnf5` is present because the base image is also the entry point for building
  and extending an Eternal system. A future `eternal-minimal` image can drop it.
- The container-only directories (`/tmp`, `/var/tmp`, `/run`, `/root`) are
  created explicitly; no package owns them until `eternal-baselayout` takes over
  the full FHS layout.
- Caches and logs from composition are removed before import so the image is a
  function of the repository, not of the build host.
