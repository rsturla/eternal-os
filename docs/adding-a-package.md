# Adding a package

## Start from a template

```console
./scripts/new-package.sh packages/foo
./scripts/new-package.sh packages/foo --template python
./scripts/new-package.sh packages/foo --template metapackage
```

The helper runs `rpmx init`, removes the per-package profile copy, and points
the recipe at `profiles/bootstrap.profile.yaml`. A package directory contains:

```text
packages/foo/
  package.yaml      # the recipe
  files/            # optional inputs copied with `context: files`
  pipelines/        # optional local step definitions
```

## Recipe anatomy

```yaml
schema: 1

package:
  name: foo
  version: "1.2.3"
  release: 1
  summary: One line about foo
  license: MIT
  source-date-epoch: 1704067200
  maintainers:
    - name: Eternal Linux maintainers
      email: maintainers@eternal.sturla.tech
  cpe:
    vendor: eternal
    product: foo

build:
  root:
    profile: ../../profiles/bootstrap.profile.yaml
  dependencies:
    tools: [bash, coreutils]
  pipeline:
    - runs: |
        install -D -m 0755 foo "$STAGE/usr/bin/foo"
    - uses: strip

outputs:
  - name: foo
    files:
      include:
        - /usr/bin/foo

tests:
  - name: smoke
    stage: build
    argv: ["foo", "--version"]
```

Rules that matter:

- `package.name` is the RPM name. Do not rename a component when Eternal takes
  ownership of it; keep the upstream/bootstrap name so `eternal-base` and
  consumers do not change.
- `source-date-epoch` is required for reproducible builds. Bump it when the
  packaged content changes.
- `build.dependencies.tools` lists **package names**, not commands: `bash`, not
  `sh`; `gcc`, not `cc`.
- Use `$STAGE` for the install root and `$PREFIX`/`$LIBDIR` for layout.
- Include a test. `rpmx build` runs tests by default, so a green build means
  tested.

See the rpmx recipe reference for the full schema:
<https://github.com/rsturla/rpmx/blob/main/docs/usage/recipes.md>.

## Sources

A recipe either uses a `context:` directory committed beside it, like
`eternal-release`, or declares `sources:` with content-addressed locators
(`https`, `file`, `git`, `go-module`). Use `rpmx bump` to move to a new upstream
version; it updates the version, URLs and digests together.

## Profile changes

Most packages need nothing beyond the bootstrap root. If a package needs an
additional build tool, add it to `build.dependencies.tools`, not to the shared
profile. Change `profiles/bootstrap.profile.yaml` only when the whole
repository needs a new toolchain component.

## Local loop

```console
./scripts/lint-all.sh
./scripts/build-all.sh --package foo --output out
./scripts/lock-all.sh
```

A package's output is `out/foo/<arch>/`. The content hash is recorded in
`out/.stamps/`, so the next `make build` skips it until a recipe, profile,
script, rpmx revision or in-tree build dependency changes. Use
`./scripts/build-all.sh --affected --since origin/main` to rebuild only what a
branch touches, or `make build-all` to force everything.

Commit `packages/foo/package.lock.json` with the recipe. CI builds with
`--locked` once the lock exists in a follow-up change; until then the lock is
recorded and reviewed.

When `foo` gains users, `scripts/package-graph.sh` picks up build edges from
`build.dependencies` and runtime edges from `outputs[].dependencies.run` via
`rpmx plan --json`; no separate dependency file to maintain.

## Pull request checklist

- [ ] `rpmx lint` is clean (warnings explained).
- [ ] The package builds with `./scripts/build-all.sh --package NAME`.
- [ ] `make affected` includes the package and anything that builds against it.
- [ ] At least one test fails if the packaged files disappear.
- [ ] `package.lock.json` is committed.
- [ ] No secrets, signing keys or local paths are in the recipe.
