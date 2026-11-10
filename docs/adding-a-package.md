# Adding a package

Read the [packaging guide](packaging.md) first. It defines the naming,
versioned-stream, subpackage, dependency, licensing and testing conventions
that recipes in this repository follow.

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

Do not put bootstrap-only versions of a package in `packages/`. A package that
is not yet buildable from the self-hosted root belongs in
`bootstrap/recipes/<name>/package.yaml` and is selected by
`bootstrap/bootstrap.yaml`. See [`../bootstrap/README.md`](../bootstrap/README.md).

## Recipe anatomy

```yaml
schema: 1

package:
  name: foo
  version: "1.2.3"
  release: 1
  summary: One line about foo
  license: MIT
  # Maintainers come from ../../rpmx-defaults.yaml.
  # cpe: only when the upstream project has one, for example:
  #   vendor: gnu
  #   product: foo

build:
  root:
    profile: ../../profiles/bootstrap.profile.yaml
  packages: [bash, coreutils]
  pipeline:
    - runs: |
        install -D -m 0755 foo "$STAGE/usr/bin/foo"
    - uses: strip

outputs:
  # The first output is the main package. It receives everything the later
  # outputs do not claim, so a single-binary package needs no files.include.
  - name: foo
    tests:
      - name: installed-smoke
        stage: installed
        environment:
          contents:
            packages: [grep]
        argv: ["sh", "-c", "foo --version | grep -q foo"]

tests:
  - name: smoke
    stage: build
    argv: ["foo", "--version"]
```

Rules that matter:

- The first output is the main package. Do not enumerate the whole runtime
  payload; split only what needs its own package. Use `@dev`, `@doc`, `@man`,
  `@info`, `@locales`, `@static`, `@pkgconfig`, `@headers` or `@debug` in
  `files.include` instead of repeating every path.
- `package.name` is the RPM name. Do not rename a component when Eternal takes
  ownership of it; keep the upstream/bootstrap name so `eternal-base` and
  consumers do not change.
- `source-date-epoch` is derived from the source archive or pinned git commit.
  Set it only when that value is wrong or when the package has no source.
- `maintainers` is repository metadata: it lives in `rpmx-defaults.yaml`, not
  in every recipe. Override it only when a package genuinely has a different
  owner.
- `cpe` identifies the **upstream** project for vulnerability matching
  (`gnu:make`, `gnu:coreutils`). Do not use the Eternal package name or
  `vendor: eternal`; omit it for Eternal-owned packages with no upstream CPE.
- `build.dependencies.tools` lists **package names**, not commands: `bash`, not
  `sh`; `gcc`, not `cc`.
- Use the reusable build steps (`autotools/configure` followed by
  `make/build`/`make/install`, or `cmake/configure` and its siblings) instead
  of copying the configure/make shell sequence into every recipe.
- Use `$STAGE` for the install root and `$PREFIX`/`$LIBDIR` for layout.
- Include a test. `rpmx build` runs tests by default, so a green build means
  tested.

See the rpmx recipe reference for the full schema:
<https://github.com/rsturla/rpmx/blob/main/docs/usage/recipes.md>.

## Tests

- `stage: build` runs in the build sandbox with the source tree. Use it for
  unit tests and checks that need the compiler or build tools.
- `stage: installed` gets its own disposable root filesystem. That root
  contains `bash`, `coreutils`, the packages in that test's `packages`, and the
  built RPMs. It does not reuse the build root.
- A test under an output installs only that output and the sibling outputs that
  provide its runtime dependencies. A recipe-level installed test installs
  every output and is useful for integration coverage.

`tests[].packages` is the only place test-root packages go; there is no
recipe-wide list. Tests with the same output and package set share one root; a
different set gets its own disposable root. `tests[].environment` sets
variables for that test's steps; a step's own `env` wins.

When several outputs reuse a test name, select one with
`rpmx test --test <output>/<name>`.

A CLI smoke test that only runs the packaged binary usually needs no extra
entry; add `procps-ng`, `grep` and so on only when the test script actually
calls them.

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

### Python packaging tools

Python modules use an rpmx `python` matrix for every interpreter stream in
`packages/`. The current streams are 3.11 through 3.15. Give each cell an RPM-safe
slug, such as `py313`, and enable `release-suffix` so each cell has a distinct
SRPM release.

Name binary outputs `python-<version>-<module>`. The default 3.14 output provides
`python-<module>`. Keep runtime dependencies specific to the interpreter.
Version installed command names so the outputs can
coexist. Use the interpreter ABI and distribution requirements that rpmx
generates from the installed Python files and wheel metadata.
Interpreter packages provide the matching `python3.X` build capability.

The packaging tools use `profiles/bootstrap-python.profile.yaml`. This profile
allows Eternal's 3.13 runtime alongside Fedora's default 3.14 interpreter.
Fedora's alternate 3.13 interpreter does not provide the required Python ABI
capability.

Use `python/build-wheel` and `python/install-wheel`. The steps select the PEP
517 backend from `pyproject.toml`, install for each target interpreter and
version commands for co-installation. They also keep RPM as the file owner.
Pure Python wheels can use the default interpreter for the build and pip.

Flit Core builds and installs itself through its upstream bootstrap commands.
Pip uses Fedora's `python3-pip` explicitly for its initial build and install.
The other foundation tools use Eternal pip as their wheel frontend. Later
recipes use the versioned Eternal build frontend and pip.
This bootstrap seed avoids self-dependencies while Eternal takes ownership of
these tools. Each matrix cell runs its tests with its target interpreter.

During the initial bootstrap, `scripts/build-all.sh` prepares unpublished
Python matrix dependencies with `scripts/build-python.py`. The helper builds
explicit interpreter-qualified package dependencies in dependency order
and adds the RPMs to a private repository for each invocation. Tests can then
use new interpreter-specific dependencies before they are published. The
helper caches tested dependencies under `.work/python-deps/` by architecture,
recipe hash and build options.

The helper's normal-build integration is temporary.
[Issue #41](https://github.com/rsturla/eternal-os/issues/41) tracks its retirement
and the replacement path for new interpreter releases. Publication alone does
not permit removal. First validate normal builds against published RPMs on
both architectures. Then remove the automatic dispatch and its cache use from
normal builds. Keep an explicit bootstrap path until rpmx can build unpublished
source dependencies for a new interpreter stream.

### Bootstrap a new Python stream

For a new stream such as 3.15, add a versioned `python-3.15` runtime recipe.
Use a Fedora seed to build the interpreter when required. Keep the existing
default in `rpmx-defaults.yaml` under `metadata.python.default-stream`.
Promote a new default only after its package set passes validation. Keep
command ownership consistent with `docs/packaging.md`.
Extend every Python module matrix with the new stream. Use `python-3.15` as
its interpreter package and `python-3.15-<project>` for module outputs.
The naming check rejects missing streams and incorrect default capabilities.

The bootstrap helper discovers versioned interpreter recipes without a fixed
version list. It builds a new interpreter before its module dependencies.
Keep the published build frontend and pip on the existing host interpreter
while installing wheels for the new target interpreter. Declare backend
dependencies explicitly, and check each upstream project's interpreter support.
Use `python/build-wheel` with `frontend: pip` and an existing Eternal pip
package to break frontend bootstrap cycles. A standalone pip zipapp can be
selected with `pip-zipapp` and an explicit owning package. Keep a seed's
archive, digest and provider policy in Eternal recipes and bootstrap profiles.
The shared rpmx steps wrap upstream tools and do not fetch implicit seeds.

After the new stream's build tools are available, build native extension
packages with that interpreter and its development files. A wheel built by
an older interpreter is not a substitute for a native extension rebuild.

For an isolated bootstrap, use a profile that permits the new Eternal runtime
and module names. Pass it through `--profile` to `scripts/build-python.py`.
The existing bootstrap profile permits new streams such as 3.15. Its 3.14
exclusion retains the current Fedora seed. Relative file repositories resolve
from the selected profile's directory.

```console
./scripts/package-graph.sh > /tmp/python-bootstrap-graph.json
./scripts/build-python.py python-hatch-vcs --arch x86_64 \
  --graph /tmp/python-bootstrap-graph.json --output out/python-hatch-vcs \
  --profile profiles/bootstrap-python.profile.yaml
```

Repeat on aarch64. Test the new stream's installed imports and commands, and
check file ownership alongside existing streams. Publish the runtime and module
RPMs, then verify normal builds without the private repository. Retire this
bootstrap implementation only after its replacement passes the same checks
with an unpublished interpreter stream.

The helper needs `/usr/bin/python3` and PyYAML. Install the `python3-yaml` host
package for local builds. The CI setup installs the same host dependency.

### Commands

```console
./scripts/lint-all.sh
./scripts/build-all.sh --package foo --output out
./scripts/build-all.sh --package foo --arch aarch64 --output out
./scripts/lock-all.sh
```

Every push to `main` rebuilds both `x86_64` and `aarch64` on native
GitHub-hosted runners; run both locally when a recipe has architecture-specific
sources or tests.

A package's output is `out/foo/<arch>/`. The content hash is recorded in
`out/.stamps/`, so the next `make build` skips it until a recipe, profile,
script, rpmx revision or in-tree build dependency changes. Use
`./scripts/build-all.sh --affected --since origin/main` to rebuild only what a
branch touches, or `make build-all` to force everything.

`packages/foo/package.lock.json` is local build metadata, not a repository
input. `./scripts/lock-all.sh` writes it, and `make lock-check` verifies it, but
the file is gitignored while the bootstrap profile follows live Fedora 44: the
recorded root closure moves whenever Fedora updates. Start committing locks
only after the bootstrap repositories or root closure are pinned and CI builds
with `--locked`.

When `foo` gains users, `scripts/package-graph.sh` picks up build edges from
`build.dependencies` and runtime edges from `outputs[].dependencies.run` via
`rpmx plan --json`; no separate dependency file to maintain.

## Pull request checklist

- [ ] The recipe changes are one commit, scoped `<name>:`, and touch no other
      `packages/` directory ([`git-workflow.md`](git-workflow.md)).
- [ ] `rpmx lint` is clean (warnings explained).
- [ ] The package builds with `./scripts/build-all.sh --package NAME`.
- [ ] `make affected` includes the package and anything that builds against it.
- [ ] At least one test fails if the packaged files disappear.
- [ ] No tracked `package.lock.json` is added while the bootstrap root floats.
- [ ] No secrets, signing keys or local paths are in the recipe.
