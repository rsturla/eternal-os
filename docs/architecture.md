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

`rpmx` packages sources before binary compilation. Release workers share one
SRPM per matrix cell across architectures. Resolved target locks travel as
separate build inputs. `rpmx rebuild <srpm> --profile PROFILE` resolves a fresh
build environment; an external target lock supplies exact pinned inputs.

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
  `$releasever` continues to mean the Eternal release. Eternal has repository
  priority 10, ahead of the Fedora fallback. When both repositories supply a
  dependency, use the Eternal package even if Fedora uses a higher version
  number. Fedora fallback repositories exclude the package families already
  adopted by the bootstrap build profile. Their exact package names can
  otherwise win over versioned Eternal providers and mix incompatible
  compiler, libc or Perl files. Standalone acceptance uses this distribution
  policy.

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

Packages that rebuild get a `+build<counter>` release suffix. Each dependency
wave advances the counter, so a follow-on rebuild never reuses an immutable
filename. Unchanged packages remain in the published repository.
Image composition is a separate pipeline.

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

Pull requests lint and build affected recipes. Releases build on `main`, using
published recipe hashes to select changes. Each package prepares its shared
SRPM, then starts native binary workers. Build tests gate those outputs.

The local transaction scheduler detects changes to public libraries, headers
and static archives. It schedules affected consumers against a fixed view of
completed candidates and repeats until the rebuild set settles. All package
acceptance runs against the completed candidate repositories. Publication uses
those exact tested bytes and keeps unchanged repository records.

Temporary build inputs use run-scoped artifacts. There are no persistent side
tags or temporary R2 repositories. Release runs are serialized. The publisher
uploads immutable objects before changing each architecture's repository index,
then records successful recipe hashes for the next release.

See [package transactions](package-transactions.md) for the state model, rebuild
policy, local commands, CI limits and cleanup. `build-all.sh` remains a direct
local build interface, including its deferred acceptance option. It does not
perform automatic transaction scheduling.

## Roadmap

1. Add `eternal-keys` once a signing key exists (see `docs/signing.md`).
2. Replace the bootstrap shell, coreutils and filesystem packages with in-tree
   recipes; shrink `profiles/bootstrap.profile.yaml` as each lands.
3. Add `aarch64` to the profiles and the CI matrix.
4. Add an `eternal-minimal` image and an `eternal-devel` image built from the
   same repository.
5. Add an ISO or bootable container image once the package set can boot.
