# Packaging guide

This is the house style for Eternal packages. It follows Wolfi's package
patterns, adapted to RPM and to rpmx. The goal is a small container-first
distribution whose recipes are predictable, reviewable and reproducible.

This guide defines the Eternal packaging model, not the current limits of
rpmx. Where the tool is stricter or less expressive, a recipe uses the closest
supported form; the workaround is not the policy.

- [`packages/`](../packages) contains the rolling recipes.
- [`bootstrap/recipes/`](../bootstrap/recipes) contains temporary bootstrap
  variants of the same package names. Stage policy never belongs in a recipe.
- [`rpmx-defaults.yaml`](../rpmx-defaults.yaml) contains repository-wide
  metadata such as maintainers.

The full recipe schema is the
[rpmx recipe reference](https://github.com/rsturla/rpmx/blob/main/docs/usage/recipes.md).

## 1. Naming and versioning

Use the upstream project name for normal packages:

```yaml
package:
  name: bash
  version: "5.3.9"
  release: 1
```

Do not rename a component when Eternal takes ownership of it. Keeping the same
name means consumers and `eternal-base` do not change as the provider moves
from the bootstrap seed to an in-tree recipe.

### Versioned package names are streams

When several upstream versions must coexist, put the stream in the package name
and provide the unversioned capability:

```yaml
package:
  name: glibc-2.44
  version: "2.44"
  release: 1

outputs:
  - name: glibc-2.44
    dependencies:
      provides:
        - glibc = ${package.version}-${package.release}
```

```yaml
package:
  name: gcc-16
  version: "16.2.0"
  release: 1

outputs:
  - name: gcc-16
    dependencies:
      provides:
        - gcc-16 = ${package.version}-${package.release}

  - name: gcc-16-default
    dependencies:
      run:
        - gcc-16 = ${package.version}-${package.release}
      provides:
        - gcc = ${package.version}-${package.release}
        - cc = ${package.version}-${package.release}
```

Rules:

- The versioned package is the implementation. The unversioned name is a
  **provide**, not a second copy.
- Use a new package name for a new ABI/toolchain stream. Do not hide a stream
  change behind `release` or `epoch` bumps.
- Declare conflicts between streams that cannot be installed together, such
  as `glibc-2.43` and `glibc-2.44`.
- The package version is the upstream version. The release starts at `1` and
  only increases for packaging changes. An epoch is only for a real upstream
  epoch or a deliberate distro-wide comparison reset.
- No `release: 100` or similar hacks to outrank the seed. Bootstrap resolver
  policy belongs in the bootstrap ladder.

### Versioned binaries

GCC is the reference for side-by-side compiler streams. Build with a program
suffix:

```yaml
--program-suffix=-16
```

so the stream owns versioned commands:

```text
/usr/bin/gcc-16
/usr/bin/g++-16
/usr/bin/cpp-16
/usr/bin/gcov-16
/usr/bin/x86_64-redhat-linux-gcc-16
```

`gcc-16-default` owns the unversioned symlinks (`gcc`, `cc`, `g++`, `c++`, ...)
and provides `gcc`/`cc`. This matches Wolfi's `gcc-N` plus `gcc-N-default`
split.

Not every versioned package versions its binaries:

- GCC, Go, Rust and similar multi-stream toolchains use versioned commands.
- glibc package and subpackage names are versioned, but commands such as
  `ldd`, `locale`, `localedef` and `iconv` keep their normal names.
- The ELF interpreter keeps its ABI name, for example
  `ld-linux-x86-64.so.2` or `ld-linux-aarch64.so.1`.

## 2. Outputs and subpackages

The build installs into `$STAGE`. An output is an RPM subpackage.

The **first output is the main package** and owns every staged file that no
other output claims. Do not enumerate the whole runtime payload, even when the
package has only one output. Subpackages are deliberate splits, not a complete
file inventory.

```yaml
outputs:
  - name: bash
    # No files.include: the runtime payload and its license stay in the main
    # package. The first output always owns the remainder.

  - name: bash-binsh
    files:
      include:
        - /usr/bin/sh
        - /usr/share/licenses/bash-binsh/COPYING

  - name: bash-doc
    files:
      include:
        - "@doc"
        - "@man"
        - "@info"
        - /usr/share/licenses/bash-doc/COPYING

  - name: bash-dev
    files:
      include:
        - "@dev"
        - /usr/bin/bashbug
        - /usr/share/licenses/bash-dev/COPYING
```

The available presets expand during planning:

| Preset | Contents |
|---|---|
| `@dev` | headers, static libraries, unversioned `.so` linker scripts, pkg-config, aclocal and CMake files |
| `@headers` | `/usr/include/**` |
| `@static` | `/usr/lib*/lib*.a` |
| `@pkgconfig` | `/usr/lib*/pkgconfig/**`, `/usr/share/pkgconfig/**` |
| `@doc` | `/usr/share/doc/**` |
| `@man` | `/usr/share/man/**` |
| `@info` | `/usr/share/info/**` |
| `@locales` | `/usr/share/i18n/**`, `/usr/share/locale/**` |
| `@debug` | `/usr/lib/debug/**`, `/usr/lib*/*.debug` |

Use explicit globs for the cases a preset does not describe. Keep selectors
narrow; do not give the main package a `/**` catch-all, because it already
collects the remainder.

### When to split

Create a subpackage only when there is a real reason:

| Output | Why |
|---|---|
| `-dev` | headers, static libraries, pkg-config and linker scripts are build-only |
| `-doc` | man pages, info pages and examples are optional |
| `-locales` | locale data is large and often unnecessary in a container |
| `-binsh` | `/bin/sh` is a separate capability from the shell package |
| `-builtins` | optional loadable modules |
| `-default` | unversioned command names for a versioned toolchain stream |
| `-lang` | translations when NLS is enabled |
| `-debuginfo` | debug information, only when `uses: debuginfo` is declared |

The main package must stay lean enough for a minimal image. A split that only
exists to satisfy a tool is not a reason to create a package.

### Ownership

- A file may belong to at most one output. Two claims are an error
  (`RPMX-OUTPUT-011`).
- An unclaimed file belongs to the main package. It is not lost.
- An output after the main package that matches no files is an error
  (`RPMX-OUTPUT-012`), unless it is a metapackage.

Review must still check that the main package did not collect development or
documentation files. The strictness belongs in review and lint policy, not in
the recipe shape.

`rpmx build` reports the file count and payload size of each output. It also
warns when the main package contains development headers, static libraries,
pkg-config/CMake files, documentation or locale source data, and names the
preset that would split them. Use `rpmx explain files` to inspect the planned
selectors and which output is the main package.

Compiler runtime archives (`libgcc.a`, `libgcc_eh.a`, `libgcov.a`) are the
exception: they stay with the compiler's main output because GCC needs them to
link, so the static-library warning is expected for that class of package.

### Every output owns its license copy

RPM cannot install two packages that claim the same path. If a subpackage is
separately installable, give it its own license copy under
`/usr/share/licenses/<output>/`:

```yaml
pipeline:
  - uses: license/copy
    with:
      files: [COPYING]
      outputs: [bash, bash-binsh, bash-doc, bash-dev, bash-builtins]
```

The main package gets its copy through the main-package fallback. A subpackage
claims its copy in `files.include` and marks it in `files.license`:

```yaml
files:
  include:
    - /usr/share/licenses/bash-dev/COPYING
  license:
    - /usr/share/licenses/bash-dev/COPYING
```

Do not point two outputs at the same license path.

## 3. Dependencies

There are four build dependency lists:

```yaml
build:
  dependencies:
    tools: [gcc, make, bash, coreutils]
    host: [glibc-devel, gmp-devel]
    target: []
    tests: [grep]
```

- `tools` are root packages needed by the pipeline: compiler, make, awk,
  generators. They are not runtime dependencies.
- `host` and `target` describe cross-build headers/libraries. For native
  builds they join the build root, but they still do not become runtime
  dependencies.
- `tests` is the package-wide list of packages every installed test needs.

Runtime dependencies belong under the output:

```yaml
outputs:
  - name: gcc-16
    dependencies:
      run:
        - binutils
        - filesystem
        - glibc-2.44-dev = 2.44-1
```

Rules:

- List package names, not commands: `bash`, not `sh`; `gcc`, not `cc`.
- Prefer capabilities (`glibc`, `gcc`) when the stream is not part of the
  interface. Pin the versioned package when mixing streams would be wrong.
- Never add a test-only package to the build root; put it on the test.
- `provides` describes what an output supplies. RPMX also generates ELF
  `libfoo.so.N()(64bit)`, script interpreter, pkg-config and similar requires.
- Do not add a runtime dependency on a development package unless the package
  genuinely cannot work without it; GCC needing glibc headers to compile is a
  deliberate exception.

## 4. Build pipeline

Use reusable steps for standard build systems. A recipe should read as the
build's decisions, not as a shell transcript:

```yaml
build:
  pipeline:
    - uses: autotools/configure
      with:
        args:
          - --with-bash-malloc=no
          - --with-afs
    - uses: autotools/build
    - uses: autotools/install
    - uses: strip
```

`autotools/configure` supplies `--prefix` and `--libdir` from the build
environment and adds `--host`/`--build` in a cross build. Use `dir` and
`configure` for out-of-tree builds:

```yaml
    - uses: autotools/configure
      with:
        dir: build
        configure: ../configure
        args: [--disable-werror]
    - uses: autotools/build
      with:
        dir: build
    - uses: autotools/install
      with:
        dir: build
```

The same pattern applies to `make/build`, `make/install`, `cmake/configure`,
`meson/setup` and their siblings. List them with `rpmx steps list` and inspect
one with `rpmx steps show autotools/configure`.

Do not inline `./configure`, `make` or `make install` when a step already does
it. If a sequence is repeated and no built-in fits, add a reusable step rather
than copying the shell block. Generic build-system steps belong in rpmx;
Eternal-specific policy does not.

### Compiler hardening

Compiler policy is a package, not a per-profile flag list. Profiles contain
repositories, packages and install paths only; they have no `flags`. The
bootstrap profile installs `openssf-compiler-options`, which puts a `gcc`
wrapper in `/usr/local/bin` and versioned GCC specs under
`/usr/lib/eternal/gcc/`. The wrapper shadows the real compiler for every C and
C++ build and applies the shared policy spec plus an architecture spec for the
target ISA baseline. Optimisation, warnings, hardening and unwind tables are
therefore all part of the root closure, and changing any of them is a package
change.

The wrapper also has the only correct place for `-pie`: GCC specs can add it
to executable links while leaving `-shared` links alone. Do not put `-pie` in
`LDFLAGS`; a shared library built after it will fail or become a broken
executable.

A package that cannot use the policy opts out explicitly:

```yaml
build:
  environment:
    GCC_SPEC_FILE: no-hardening.spec
```

GCC packages use `openssf-soft-format-<major>.spec`: it applies the same
policy while keeping the compiler's own `-Werror=format-security` diagnostics
non-fatal. Use the absolute `/usr/lib/eternal/gcc/openssf-<major>.spec` path
only when a test needs to exercise one compiler stream directly. Packages that
ship ELF files assert the result with `test/hardening-check`; compiler-options
packages use `test/compiler-hardening-check`.

## 5. Source, identity and metadata

```yaml
package:
  summary: The GNU Bourne Again SHell
  license: GPL-3.0-or-later
  upstream: https://www.gnu.org/software/bash/
  cpe:
    vendor: gnu
    product: bash
```

- `source-date-epoch` is optional. rpmx derives it from the newest source
  archive mtime or the pinned git commit time. Set the field only to override
  that value. Packages with no upstream source use the repository fallback in
  `rpmx-defaults.yaml`; a bootstrap stage may override the effective value.
- `cpe` identifies the **upstream** project, not Eternal. Use `gnu:make`, never
  `eternal:make`.
- Do not put maintainers in every recipe. They live in `rpmx-defaults.yaml`.
- Prefer content-addressed `sources` with a SHA-512 digest and at least two
  HTTPS mirrors. The digest verifies either mirror, so a slow or unavailable
  host is a retry, not a failed build. `context: files` is for small
  Eternal-owned files.
- Keep patches under the package directory. Upstream patches that rely on
  significant whitespace are exempt from the repository's
  trailing-whitespace hook.

### Source selection

Default to the artifact upstream publishes, not to a git branch:

1. Use the official release tarball when upstream publishes one, even when a
   git tag exists for the same version.
2. Use the upstream patch release when upstream publishes one (`gcc-16.2.0`,
   `binutils-2.46.1`, `make-4.4.1`, `coreutils-9.10`).
3. Keep the release tarball and apply the upstream numbered patch series when
   upstream publishes patches but no refreshed tarball (Bash).
4. Use a pinned git commit only when upstream maintains a stable branch but
   does not publish patch-level tarballs. glibc is the current example: pin
   `release/2.43/master` or `release/2.44/master`, record the full commit, and
   comment the branch in the recipe.

Do not default every package to git. A git checkout is not the artifact
upstream tested, may omit generated files such as `configure`, and turns
source selection into an arbitrary branch snapshot. Prefer releases because
they are stable, mirrored and already include generated build files.

Every source still needs a SHA-512 digest. For a git source, rpmx stores the
deterministic archive in the CAS and records that archive's digest. Git
locators may have a single URL when no equivalent mirror exists; the full
commit and digest still pin the content.

## 6. Filesystem layout

Eternal uses a merged `/usr`:

```text
/bin   -> usr/bin
/sbin  -> usr/sbin
/lib   -> usr/lib
/lib64 -> usr/lib64
/var/run -> ../run
/var/lock -> ../run/lock
```

Packages should install into `/usr` and use `$PREFIX`/`$LIBDIR` where possible.
The `filesystem` package owns the top-level FHS directories and symlinks;
packages own their own subdirectories. Do not claim a directory in two outputs.

For x86_64, use `/usr/lib64` for 64-bit libraries; for aarch64, `/usr/lib`.
Build steps can branch on `${arch}`:

```yaml
- runs: |
    case "${arch}" in
      x86_64) libdir=/usr/lib64 ;;
      *) libdir=/usr/lib ;;
    esac
```

## 7. Tests

Every package needs at least one test that would fail if its primary behavior
were missing or broken.

- `stage: build` runs in the build sandbox with the source tree. Use it for
  compilation and unit checks.
- `stage: installed` gets a disposable root containing the built RPMs plus its
  test dependencies. Use it for command-level smoke tests.

Add an output-level test when the output has a user-facing command or runtime
behavior. A `-doc`, `-locales` or empty metapackage output does not need an
artificial test of its own; a package-level integration test can cover it.

```yaml
outputs:
  - name: gcc-16
    tests:
      - name: installed
        stage: installed
        argv: ["gcc-16", "--version"]

  - name: gcc-16-default
    tests:
      - name: installed
        stage: installed
        argv: ["sh", "-c", "gcc --version && cc --version"]
```

Only add `environment.contents.packages` when the test actually invokes those
packages. A simple binary smoke test usually needs no extra test packages.

Tests must not rely on the network.

## 8. Versioned toolchain example: GCC 16

The important parts of a versioned compiler recipe:

```yaml
package:
  name: gcc-16
  version: "16.2.0"

build:
  pipeline:
    - runs: |
        case "${arch}" in
          x86_64) libdir=/usr/lib64 ;;
          *) libdir=/usr/lib ;;
        esac
        mkdir build && cd build
        ../configure \
          --prefix=/usr \
          --libdir="$libdir" \
          --program-suffix=-16 \
          --enable-languages=c,c++ \
          --disable-bootstrap
        make -j"$JOBS"
        make install DESTDIR="$STAGE"

outputs:
  - name: gcc-16
    # Main package: compiler, runtime and everything not split out below.
    dependencies:
      provides:
        - gcc-16 = ${package.version}-${package.release}

  - name: gcc-16-default
    files:
      include:
        - /usr/bin/gcc
        - /usr/bin/cc
        - /usr/bin/g++
        - /usr/bin/c++
    dependencies:
      run:
        - gcc-16 = ${package.version}-${package.release}
      provides:
        - gcc = ${package.version}-${package.release}
```

Use `--disable-bootstrap` for the first import; a later toolchain-generation
job can rebuild GCC with itself.

## 9. Versioned ABI example: glibc

Keep both supported glibc streams as separate recipes:

```text
packages/glibc-2.43/package.yaml
packages/glibc-2.44/package.yaml
```

Both provide `glibc`, and each runtime output conflicts with the other stream.
Each stream owns its own versioned subpackages:

```text
glibc-2.44
glibc-2.44-dev
glibc-2.44-iconv
glibc-2.44-locales
glibc-2.44-doc
ld-linux-2.44
libc-bin-2.44
nss-db-2.44
```

The main `glibc-2.44` output has no `files.include`; it owns the runtime
libraries, `/etc/rpc` and the license. Optional data is split by purpose:

```yaml
  - name: glibc-2.44-locales
    files:
      include:
        - "@locales"
        - /usr/share/licenses/glibc-2.44-locales/COPYING
```

Keep the unversioned capability on the runtime package:

```yaml
dependencies:
  conflicts:
    - glibc-2.43
  provides:
    - glibc = ${package.version}-${package.release}
```

Packages that must link against a specific stream depend on the versioned dev
package (`glibc-2.44-dev = 2.44-1`), not only on `glibc`.

## 10. Bootstrap variants

Every package that participates in the bootstrap ladder has two definitions:

```text
packages/foo/package.yaml
bootstrap/recipes/foo/package.yaml
```

- `packages/foo` is the rolling production recipe.
- `bootstrap/recipes/foo` may pin a different release, build root or tool list
  while the seed is still in use.

Do not move a package between the two directories. Keep the same output name
and provides. Stage order, seed replacements and fixed-point iteration belong
in `bootstrap/bootstrap.yaml`, not in either recipe.

When the production recipe can build from the self-hosted root, delete the
bootstrap variant; the production recipe stays.

## 11. Review checklist

- [ ] Package name follows upstream; a versioned stream is explicit.
- [ ] Unversioned capabilities are provided by the versioned/default output.
- [ ] Runtime output contains no docs, headers, static libraries or build
      tools; use the split presets instead of listing every path. Compiler
      runtime archives needed for linking are the exception.
- [ ] Every separately installable output has its own license copy and claims
      it in `files.include` and `files.license`.
- [ ] Every user-facing output has a test, or the package-level test covers it.
      Doc, locale and metapackage outputs are exempt.
- [ ] Build dependencies are package names; test-only packages are on tests.
- [ ] `source-date-epoch` is explicit, derivable from the source, or covered
      by the repository fallback; `cpe` names the upstream project.
- [ ] The source is the upstream release artifact, or a pinned git commit with
      a documented reason.
- [ ] No maintainers, local paths, secrets or bootstrap stage logic.
- [ ] The commit changes this package only, and its `scope:` names it; see
      [`git-workflow.md`](git-workflow.md).
- [ ] `rpmx lint` is clean.
- [ ] No tracked `package.lock.json` is added while the bootstrap root floats.
- [ ] The package builds on both x86_64 and aarch64 in CI.
