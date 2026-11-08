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
  repodata (object storage) ->  dnf install --installroot  ->  OCI image (separate pipeline)
```

## Building blocks

| Concern | Owner |
| --- | --- |
| Rolling package recipes | `packages/<name>/package.yaml` |
| Bootstrap recipes | `bootstrap/recipes/<name>/package.yaml` |
| Bootstrap ladder | `bootstrap/bootstrap.yaml` (stages, roots, seed mapping) |
| Build roots | `profiles/bootstrap.profile.yaml` (toolchain) |
| Distribution repositories | `profiles/eternal.profile.yaml` |
| Package repository | S3-compatible object storage, `https://packages.eternal.sturla.tech/` |
| Images | A separate image pipeline, outside `release.yml` |
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
- Its `dist-tag` is `.eternal`, so the RPMs it produces are Eternal packages,
  not Fedora packages.
- `profiles/eternal.profile.yaml` lists the bootstrap repositories separately
  from the Eternal repository, pinned to Fedora 44 literally so that
  `$releasever` continues to mean the Eternal release.

Self-hosting means removing the bootstrap repositories and every bootstrap
dependency. Usually a package keeps the name of the component it replaces
(`bash`, `coreutils`, `glibc`, `filesystem`, `dnf5`), so `eternal-base` does not
change as ownership moves in-tree. When the names differ, the stage's
`replaces` map says which seed package the Eternal output supersedes, and the
recipe must provide the seed name so dependencies still resolve.

Bootstrap recipes are a separate definition, not normal recipes with bootstrap
flags. They can carry a different epoch, release, source timestamp, build root
and build-tool list. A recipe graduates to `packages/` when the self-hosted
root can build the rolling package.

## Release channels

The rolling repository is laid out as `<releasever>/<basearch>`, with a
parallel archive at `archive/<basearch>`:

```text
https://packages.eternal.sturla.tech/rolling/x86_64/
https://packages.eternal.sturla.tech/archive/x86_64/
```

Eternal is a rolling distribution, so `releasever` is literally `rolling`.
Every push to `main` replaces the `rolling` repository at that path. A second,
disabled-by-default `archive` repository keeps every historical EVR so users can
pin or downgrade without losing the package set that was current at the time:

```console
dnf --enablerepo=eternal-archive install foo-<version>
dnf --enablerepo=eternal-archive downgrade foo
```

Packages that rebuild in a release run get `+build<Unix timestamp>` appended to
their release, so a dnf client sees a newer NEVRA. One timestamp is computed
per release run and shared by every package that rebuilds; unchanged packages
are restored from the content-addressed cache and keep their previous NEVRA.
Image composition is a separate pipeline and is not part of `release.yml`.

Release identity lives in `packages/eternal-release`:

- `/etc/os-release`, `/etc/system-release`, `/etc/redhat-release`;
- `/etc/yum.repos.d/eternal.repo`;
- the `system-release` provides and the obsoletes that replace the bootstrap
  release package.

## Images

An image is a package set, not a Dockerfile, and the set is the `eternal-base`
recipe, so an image definition is a recipe review. Composition lives in a
separate repository: it installs `eternal-base` from a published package
repository, so every image is a function of a specific repository state and
never of a branch checkout. A bad package cannot reach an image before it
reaches the repository.

This repository stops at the published repository. OCI import, tags and
manifest lists are not part of `make` or of `release.yml`, so nothing here needs
`podman` for image work.

## Pipeline

CI runs the same scripts a developer runs. `make check`, `make build` and
`make repo` are the release interfaces; the workflows add only secret
materialization, artifact transfer between jobs and object-storage credentials.

`ci.yml` runs on pull requests and on demand:

- check the commits against the conventions in
  [`git-workflow.md`](git-workflow.md) (`scripts/check-commits.sh`);
- lint every recipe with `rpmx lint` (`make check` also runs pre-commit);
- `prepare` computes the affected package list and content hashes from the
  recipe graph (`scripts/affected.sh`, `scripts/package-graph.sh`);
- a matrix builds only the affected packages in parallel, which runs the
  recipe's tests by default, and uploads per-package artifacts.

`release.yml` runs on `main`, on `v*` tags and on demand:

1. lint, then run the full package matrix. Each package restores its
   content-addressed cache, so only changed packages execute `rpmx build`.
   Signing is applied when `RPMX_SIGNING_KEY` is set;
2. the fan-in verifies that every package in the plan produced artifacts, then
   assembles and signs `repodata` in `site/`;
3. uploads `rolling` and appends the new RPMs to `archive` in S3-compatible
   object storage.

Image composition is a separate pipeline. It consumes the published package
repository; it is not a step in `release.yml`.

### Incremental model

```text
rpmx plan --json  ->  graph (build + run edges)
        |
        v
git diff  ->  affected.sh  ->  matrix JSON  ->  build-all.sh
                                                    |
                                content hash  <-----+
                                                    |
                                                    v
                                        out/.stamps + CI cache keys
```

The hash covers the recipe bundle, profiles, build scripts, pinned rpmx and
the transitive hashes of in-tree build dependencies. Two builds with the same
hash are interchangeable. A missing cache is safe: it only causes a rebuild.
The `rolling` repository is the mutable latest view; `archive` is append-only
and preserves historical EVRs. Each release is still reproducible from the
artifacts and the `+build<timestamp>` release counter.

GitHub's matrix job outputs merge cells into a map, but only for statically
declared output names. With a dynamic package matrix, the plan and hashes are
produced once by `prepare` and exposed as reusable-workflow outputs; the RPMs
travel as artifacts. A future persistent repository or OCI registry can
replace the artifact hop without changing the recipe model.

The image package set is the `eternal-base` recipe, consumed by the image
repository. An image is built from a published repository, so a bad package
cannot slip into an image before the repository is published.

### Why not Buck2 yet?

The package graph and content-addressed cache above are deliberately small:
about 200 lines of shell around `rpmx plan --json` and `git ls-files`. They give
the properties that matter today: affected-package selection, correct
invalidation, local/CI parity and a safe fallback (a cache miss means a
rebuild).

A general build system such as Buck2 or Bazel would replace them with a proper
action graph, hermetic input declaration and a remote cache. The blocker is not
the graph; it is that an `rpmx build` action is not hermetic: it needs
`podman` to resolve and assemble the build root (network) and `bubblewrap` to
run steps (namespaces). Remote execution workers usually cannot nest those
privileges. Adopting Buck2 now would mean writing Starlark rules around a
non-hermetic action and still running everything locally.

The migration path is:

1. keep recipes and `rpmx` as the unit of work;
2. make the build root a declared input (resolve once, hash the assembled
   root) so a build action has no network;
3. move root assembly and image composition to tasks that are allowed to be
   non-hermetic;
4. then wrap package actions in a real build system and point CI and developers
   at the same remote cache.

Until then, the shell entry points are intentionally boring and reviewable.

## Roadmap

1. Add `eternal-keys` once a signing key exists (see `docs/signing.md`).
2. Replace the bootstrap shell, coreutils and filesystem packages with in-tree
   recipes; shrink `profiles/bootstrap.profile.yaml` as each lands.
3. Add `aarch64` to the profiles and the CI matrix.
4. Add an `eternal-minimal` image and an `eternal-devel` image built from the
   same repository.
5. Add an ISO or bootable container image once the package set can boot.
