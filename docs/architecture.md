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
- Its `dist-tag` is `.eternal`, so the RPMs it produces are Eternal packages,
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
https://rsturla.github.io/eternal-os/rolling/x86_64/
```

Eternal is a rolling distribution, so there is one channel: `rolling`.
`releasever` is literally `rolling`, and every push to `main` replaces the
repository at that path. There is no stable/updates split yet.

Packages that rebuild in a release run get `+build<run-number>` appended to
their release, so a dnf client sees a newer NEVRA. Unchanged packages are
restored from the content-addressed cache and keep their previous NEVRA. The
image is published as a multi-arch manifest under `:rolling`, `:latest` and an
immutable `:sha-<commit>` tag.

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

`ci.yml` runs on pull requests and on demand:

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
3. deploys `site/` to GitHub Pages and keeps it as a workflow artifact;
4. composes the base image per architecture (native x86_64 and aarch64
   runners) and pushes a multi-arch manifest to GHCR.

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
There is no mutable "latest repository" state; the published repository is
assembled from the artifacts of the current run.

GitHub's matrix job outputs merge cells into a map, but only for statically
declared output names. With a dynamic package matrix, the plan and hashes are
produced once by `prepare` and exposed as reusable-workflow outputs; the RPMs
travel as artifacts. A future persistent repository or OCI registry can
replace the artifact hop without changing the recipe model.

The image package set is `images/base/packages.txt`, shared by `make image`
and CI. The image is built from the repository produced in the same run, so a
bad package cannot slip into an image before the repository is published.

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
