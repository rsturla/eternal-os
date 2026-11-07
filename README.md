# Eternal OS

Eternal Linux is a greenfield, package-first Linux distribution. It is built
the way [Wolfi](https://github.com/wolfi-dev) is built, but with RPM packages
produced by [rpmx](https://github.com/rsturla/rpmx):

- every package is a reviewed, strict YAML recipe in `packages/`;
- a single GitHub Actions run builds, tests, signs and publishes an RPM
  repository;
- OCI images are composed from that repository rather than hand-written
  Dockerfiles layering on another distribution;
- everything is reproducible, SBOM'd and signed.

> [!IMPORTANT]
> Eternal Linux is in its bootstrap phase. Packages and images are currently
> built against a Fedora 44 **bootstrap root** (`profiles/bootstrap.profile.yaml`)
> because rpmx needs a working glibc toolchain and a package manager to start
> from. The bootstrap root is a build dependency, not the distribution's
> identity: Eternal owns its release package, repository, package set and
> images. As packages are brought in-tree they replace their bootstrap
> counterparts without renaming them, and the bootstrap root shrinks.

## Status

| Area | State |
| --- | --- |
| Package recipes | `eternal-release`, `eternal-baselayout`, `eternal-base` |
| Repository | Published to GitHub Pages at `https://rsturla.github.io/eternal-os/44/$basearch` |
| Images | `ghcr.io/rsturla/eternal-os/base:44` |
| Architectures | `x86_64` (the layout is ready for `aarch64`) |
| Signing | Optional in CI and locally; see [`docs/signing.md`](docs/signing.md) |

## Repository layout

```text
.
├── .github/
│   ├── actions/setup-rpmx/       # pinned rpmx + host toolchain
│   └── workflows/
│       ├── _build-packages.yml    # reusable package build
│       ├── ci.yml                 # lint and build every package on a PR
│       └── release.yml            # sign, publish the repo, push the image
├── docs/
│   ├── adding-a-package.md
│   ├── architecture.md
│   └── signing.md
├── images/base/                   # base image definition and docs
├── packages/                      # one directory per recipe (source of truth)
├── profiles/
│   ├── bootstrap.profile.yaml     # Fedora 44 build root (temporary)
│   └── eternal.profile.yaml       # the Eternal repository (for consumers)
├── scripts/                       # local and CI entry points
└── Makefile
```

Build output goes to `out/<arch>/`; the published repository mirror is written
to `site/`. Both are ignored by Git.

## Quick start

Requirements: Linux, Rust 1.88+, `podman`, `bubblewrap`, `dnf5` and `tar`.
Root resolution and test roots run through `podman`; build steps run through
`bubblewrap`. `rpmx doctor` checks the host.

```console
make bootstrap     # cargo install the pinned rpmx revision
make doctor        # check podman/bubblewrap/dnf5
make check         # pre-commit + lint every recipe
make build         # build every package into out/<arch>/
make repo          # assemble site/44/<arch>/ with repodata
make image         # compose ghcr.io/rsturla/eternal-os/base:44
make all           # check + build + repo + image
```

The first build resolves the bootstrap root (network, a few minutes). Later
builds reuse the cached root. The pinned rpmx revision lives in
`.rpmx-revision`; Renovate manages it.

Build one package:

```console
./scripts/build-all.sh --package eternal-release --output out
```

## Local and CI run the same commands

There is no CI-only build logic. Every workflow step calls a script in
`scripts/`:

| Local | CI |
| --- | --- |
| `make bootstrap` | `./.github/actions/setup-rpmx` calls `scripts/install-rpmx.sh` |
| `make check` | `scripts/lint-all.sh` + `pre-commit` |
| `make build` | `scripts/build-all.sh`, one matrix job per package |
| `make repo` | `scripts/publish-repo.sh` |
| `make image` | `scripts/build-image.sh` |
| `make push` | the same script with `--push` |

The package matrix comes from `scripts/list-packages.sh`, the image package
set from `images/base/packages.txt`, and the rpmx revision from
`.rpmx-revision`. A local build and a CI build therefore consume exactly the
same inputs.

The only difference is secret delivery. CI writes `RPMX_SIGNING_KEY` and
`RPMX_PUBLIC_KEY` to temporary files; locally, pass the files directly:

```console
./scripts/build-all.sh --signing-key ~/eternal-signing-key.asc
./scripts/publish-repo.sh --packages out --output site --release 44 \
  --signing-key ~/eternal-signing-key.asc \
  --public-key ~/eternal-signing-key.asc.pub
```

## How a release works

1. `ci.yml` lints every recipe and builds each package in a matrix on every PR.
2. `release.yml` runs on `main`, on `v*` tags and on demand:
   - builds every package, signing with `RPMX_SIGNING_KEY` when the secret is
     configured;
   - rebuilds `repodata` into `site/44/<arch>/`, signs `repomd.xml` when a key
     is available, and writes `eternal.repo`, `RPM-GPG-KEY-eternal` and
     `.nojekyll` beside it;
   - deploys `site/` to GitHub Pages;
   - composes the base image from the just-built repository and pushes it to
     GHCR.

Packages are always built from source; the repository is the only artifact
consumers see.

## Packages and profiles

A recipe declares its build root. All in-tree packages currently use:

```yaml
build:
  root:
    profile: ../../profiles/bootstrap.profile.yaml
```

`profiles/eternal.profile.yaml` describes the distribution's own repositories
(the published Eternal repo plus the bootstrap repositories still needed by the
initial package set). It is what an image or a future self-hosting package
consumes.

To add a package, run:

```console
./scripts/new-package.sh packages/foo
```

and read [`docs/adding-a-package.md`](docs/adding-a-package.md).

## Images

`images/base/` defines the distribution's base image as a package set, not a
Dockerfile. `scripts/build-image.sh` installs that set into a fresh root with
`dnf5 --installroot`, imports the result as an OCI image and tags it. This is
the apko-style half of the Wolfi model.

The image currently bootstraps the userspace from Fedora 44 while Eternal
packages provide the identity and layout. The package list lives in
`packages/eternal-base/package.yaml`; taking ownership of a bootstrap package
means adding a recipe with the same name and dropping it from the bootstrap
repositories once the whole set is self-hosting.

## Signing and keys

Signing is optional so a fork can build immediately, but a production
repository must be signed. Generate a key, store the private half as
`RPMX_SIGNING_KEY` and the public half as `RPMX_PUBLIC_KEY`, and flip
`gpgcheck=1` in `packages/eternal-release/files/eternal.repo`. Full steps:

```console
see docs/signing.md
```

## License

MIT. See [`LICENSE`](LICENSE).
