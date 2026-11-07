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
| Release model | Rolling: every push to `main` republishes the `rolling` channel |
| Repository | Rolling channel at `https://rsturla.github.io/eternal-os/rolling/$basearch` |
| Images | Composed by a separate image pipeline, not by this release workflow |
| Architectures | `x86_64` and `aarch64` (GitHub-hosted ARM runners) |
| Signing | Optional in CI and locally; see [`docs/signing.md`](docs/signing.md) |

## Repository layout

```text
.
├── .github/
│   ├── actions/setup-rpmx/       # pinned rpmx + host toolchain
│   └── workflows/
│       ├── _lint.yml              # reusable lint (pre-commit + rpmx lint)
│       ├── _build-packages.yml    # plan + affected matrix + per-package build
│       ├── ci.yml                 # affected packages on a PR
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
│   ├── affected.sh                # package selection from a git diff
│   ├── package-graph.sh           # in-tree build/run edges from rpmx plan
│   ├── package-hash.sh            # content hashes and cache keys
│   ├── build-all.sh               # incremental per-package builds
│   └── ...
└── Makefile
```

Build output goes to `out/<package>/<arch>/`; the published repository mirror
is written to `site/`. Both are ignored by Git.

## Quick start

Requirements: Linux, Rust 1.88+, `podman`, `bubblewrap`, `dnf5` and `tar`.
Root resolution and test roots run through `podman`; build steps run through
`bubblewrap`. `rpmx doctor` checks the host.

```console
make bootstrap     # cargo install the pinned rpmx revision
make doctor        # check podman/bubblewrap/dnf5
make check         # pre-commit + lint every recipe
make build         # build only packages whose content hash changed
make repo          # assemble site/rolling/<arch>/ with repodata
make all           # check + build + repo
# image composition is a separate pipeline; `make image` is local-only
```

The first build resolves the bootstrap root (network, a few minutes). Later
builds reuse the cached root. The pinned rpmx revision lives in
`.rpmx-revision`; Renovate manages it.

Build one package, or only the packages touched since a ref:

```console
./scripts/build-all.sh --package eternal-release --output out
./scripts/build-all.sh --affected --since origin/main --output out
```

Per-package artifacts land in `out/<package>/<arch>/`. Keeping package outputs
separate matters: an installed-stage test root must not see RPMs from unrelated
packages.

## Incremental builds

Every package has a content hash over its recipe, context, lock, profiles,
build scripts, the pinned rpmx revision, and its in-tree build dependencies
transitively. `scripts/build-all.sh` records the hash in `out/.stamps/` and
skips a package when the stamp matches and its RPMs are present.

```console
make hash            # content hashes, one per package
make affected        # packages affected since BASE (default origin/HEAD)
make build           # consider every package, skip unchanged ones
make build-affected  # only packages affected since BASE
make build-all       # force a full rebuild
```

`scripts/affected.sh` walks the package graph from `rpmx plan --json`: a
recipe change rebuilds that package plus everything that builds against it;
a profile, script or rpmx revision change rebuilds everything. Runtime
dependents are only followed with `--with-runtime-dependents`, because a
version-only change does not alter their NEVRA.

CI uses the same hash as a cache key. The release matrix still covers every
package so the published repository is complete, but unchanged packages are
restored from cache without running `rpmx build`.

## Local and CI run the same commands

There is no CI-only build logic. Every workflow step calls a script in
`scripts/`:

| Local | CI |
| --- | --- |
| `make bootstrap` | `./.github/actions/setup-rpmx` calls `scripts/install-rpmx.sh` |
| `make check` | `_lint.yml` calls `scripts/lint-all.sh` + `pre-commit` |
| `make build` / `build-affected` | `_build-packages.yml` calls `scripts/build-all.sh` |
| `make repo` | `scripts/publish-repo.sh` |

The plan comes from `scripts/list-packages.sh`, `scripts/affected.sh`,
`scripts/package-graph.sh` and `scripts/package-hash.sh`; the rpmx revision
from `.rpmx-revision`. A local build and a CI build therefore consume exactly
the same inputs. Local image composition additionally reads
`images/base/packages.txt`; image publishing is separate.

The only difference is secret delivery. CI writes `RPMX_SIGNING_KEY` and
`RPMX_PUBLIC_KEY` to temporary files; locally, pass the files directly:

```console
./scripts/build-all.sh --signing-key ~/eternal-signing-key.asc
./scripts/publish-repo.sh --packages out --output site --release rolling \
  --signing-key ~/eternal-signing-key.asc \
  --public-key ~/eternal-signing-key.asc.pub
```

## How a release works

`ci.yml` runs on pull requests and on demand. A `prepare` job computes the
package plan and hashes, then a matrix builds only the affected packages in
parallel and uploads each package's artifacts. Lint runs first as a reusable
workflow.

`release.yml` runs on `main`, on `v*` tags and on demand:

1. lint, then build **every** package in a matrix. Content-addressed caches
   mean only changed packages execute `rpmx build`.
2. A fan-in job downloads the per-package artifacts, verifies that the plan is
   complete, and rebuilds `repodata` into `site/rolling/<arch>/` plus
   `site/rolling/SRPMS/`. When a key is configured it signs the RPMs and
   `repomd.xml`, and writes `eternal.repo`, `RPM-GPG-KEY-eternal` and
   `.nojekyll` beside it.
3. deploys `site/` to GitHub Pages.

Eternal is a rolling distribution: every push to `main` republishes the
`rolling` channel. Packages that actually rebuild get a `+build<Unix timestamp>`
release suffix so `dnf upgrade` always sees a newer NEVRA; unchanged packages
are restored from cache. Image composition is a separate pipeline and is not
part of `release.yml`.

GitHub's matrix job outputs merge cells into a map, but only for statically
declared output names. A dynamic package matrix cannot name one output per
package, so the plan and hashes are produced once by `prepare` and the RPMs
travel as artifacts. The fan-in uses the plan as its completeness check.

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
