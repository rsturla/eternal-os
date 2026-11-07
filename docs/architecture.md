# Architecture

Eternal Linux is a package-first distribution. Packages are the product; images
are a view of a package set. Nothing in the repository is a hand-maintained
root filesystem.

```text
package.yaml + profile + sources
        |
        v
   rpmx build  ->  signed RPMs + SRPMs + SBOMs
        |
        v
  repodata (GitHub Pages)  ->  dnf install --installroot  ->  OCI image (GHCR)
```

## Building blocks

| Concern | Owner |
| --- | --- |
| Package recipes | `packages/<name>/package.yaml` in this repository |
| Build roots | `profiles/bootstrap.profile.yaml` (toolchain) |
| Distribution repositories | `profiles/eternal.profile.yaml` |
| Package repository | GitHub Pages, `https://rsturla.github.io/eternal-os/` |
| Images | GHCR, `ghcr.io/rsturla/eternal-os/base` |
| CI/CD | `.github/workflows/` |

`rpmx` always produces a native SRPM first. `rpmx rebuild <srpm>` can reproduce
a binary without this checkout, which is what makes an archived SRPM a real
release artifact.

## Bootstrap versus distribution

rpmx needs a running build root: a shell, a compiler, `dnf5`, glibc. A brand-new
distribution cannot provide those on day one, so the first recipes build inside
a Fedora 44 root.

The bootstrap root is deliberately contained:

- It is named `bootstrap-*`, never `eternal-*`.
- It only supplies the build toolchain and the packages `eternal-base` still
  needs.
- Its `dist-tag` is `.eternal44`, so the RPMs it produces are Eternal packages,
  not Fedora packages.
- `profiles/eternal.profile.yaml` lists the bootstrap repositories separately
  from the Eternal repository, pinned to Fedora 44 literally so that
  `$releasever` continues to mean the Eternal release.

Self-hosting means removing the bootstrap repositories and every bootstrap
dependency. Package names are chosen to match the components they replace
(`bash`, `coreutils`, `glibc`, `filesystem`, `dnf5`), so `eternal-base` does not
change as ownership moves in-tree.

## Release channels

The repository is laid out as `<releasever>/<basearch>`:

```text
https://rsturla.github.io/eternal-os/44/x86_64/
```

Today there is one channel: `eternal`. A future `eternal-updates` channel gets
its own directory and its own `.repo` stanza; consumers opt in.

Release identity lives in `packages/eternal-release`:

- `/etc/os-release`, `/etc/system-release`, `/etc/redhat-release`;
- `/etc/yum.repos.d/eternal.repo`;
- the `system-release` provides and the obsoletes that replace the bootstrap
  release package.

## Images

`scripts/build-image.sh` composes an image instead of building one with a
Dockerfile:

1. create an empty root;
2. run `dnf5 --installroot` in a bootstrap container against the just-built
   repository (plus the bootstrap repositories still needed);
3. remove package-manager caches and add the container-only directories;
4. import the root as an OCI image and tag it.

The package list is `eternal-base`, so the image definition is a recipe review,
not a Dockerfile review. Every image is a function of the repository that was
published in the same workflow run.

## Pipeline

CI runs the same scripts a developer runs. `make check`, `make build`,
`make repo` and `make image` are the interfaces; the workflows add only secret
materialization, artifact transfer between jobs and the GitHub Pages/GHCR
credentials.

`ci.yml` runs on every pull request:

- lint every recipe with `rpmx lint` (`make check` also runs pre-commit);
- build every package in a matrix from `scripts/list-packages.sh`, which runs
the recipe's tests by default.

`release.yml` runs on `main`, on `v*` tags and on demand:

1. build every package in a matrix, signing when `RPMX_SIGNING_KEY` is set;
2. assemble and sign `repodata` in `site/`;
3. deploy `site/` to GitHub Pages and keep it as a workflow artifact;
4. compose the base image from that repository and push it to GHCR.

The image package set is `images/base/packages.txt`, shared by `make image`
and CI. The image is built from the repository produced in the same run, so a
bad package cannot slip into an image before the repository is published.

## Roadmap

1. Add `eternal-keys` once a signing key exists (see `docs/signing.md`).
2. Replace the bootstrap shell, coreutils and filesystem packages with in-tree
   recipes; shrink `profiles/bootstrap.profile.yaml` as each lands.
3. Add `aarch64` to the profiles and the CI matrix.
4. Add an `eternal-minimal` image and an `eternal-devel` image built from the
   same repository.
5. Add an ISO or bootable container image once the package set can boot.
