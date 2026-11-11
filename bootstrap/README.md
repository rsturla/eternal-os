# Bootstrap build definition

This directory is the dedicated, stage-oriented build definition for bringing
Eternal up from the pinned Fedora seed. It is intentionally separate from
`packages/`, which keeps the production/rolling definition for the same
package name:

- `bootstrap.yaml` is the ladder. It owns stage order, roots, repositories,
  fixed-point packages, and the seed-package mapping (`replaces`).
- `recipes/` holds bootstrap build definitions. A bootstrap recipe may pin an
  epoch, release, build root, or build-tool list that would be wrong for the
  rolling package of the same output name. The ladder owns the source timestamp.
- `profiles/` holds profiles used only by a bootstrap stage. The general Fedora
  seed build root remains `../profiles/bootstrap.profile.yaml`, because normal
  packages use it too.

`bootstrap.yaml` owns the effective timestamp and a stage may override it.
Standalone `rpmx lint`/`rpmx build` derives the value from the source archive
or pinned git commit; the stage value takes precedence when the ladder runs.

`replaces` is the contract between Eternal output names and seed package names.
They do not have to match. For example, if Eternal shipped `eternal-foo` while
Fedora shipped `foo`:

```yaml
replaces:
  eternal-foo: foo
```

The recipe must also declare the seed name in `provides` so dependencies that
still say `foo` resolve to the Eternal package. The mapping only controls which
provider the bootstrap resolver is allowed to see; it does not create RPM
metadata.

The same output name may exist in both places. `packages/<name>/package.yaml`
is the production recipe; `bootstrap/recipes/<name>/package.yaml` is the
bootstrap variant. Keep bootstrap-only epoch/release/build dependencies in the
variant rather than leaking them into the production recipe. When the variant
is no longer needed, delete it; the production recipe stays.

Build locally with:

```console
make bootstrap-plan
make bootstrap-build
make bootstrap-build ARCH=aarch64
make bootstrap-clean
```

The equivalent direct commands are `rpmx bootstrap plan bootstrap/bootstrap.yaml`
and `rpmx bootstrap build bootstrap/bootstrap.yaml --arch <arch>`.

## Go compiler transition

The Go stages follow the existing userspace stages:

- `go-seed` builds both streams from `recipes/golang-1.26/` and
  `recipes/golang-1.27/` with Fedora's `golang-bin` compiler.
- `go-selfhost` selects the production recipes under `../packages/` explicitly.
  Both use the versioned Eternal `go-1.26` command from the seed output.
  Provider exclusions hide published copies of these streams so the local
  stage output supplies the compiler. Fixed-point passes then rebuild both
  streams with this stage's own output.

The production recipes need no default selector. Normal builds consume the
published Eternal `golang-1.26` package. The ladder remains the explicit path
to recreate that compiler from Fedora when the Eternal package is unavailable.
Keep the bootstrap variants' sources, patches, flags and tests in sync with
the production streams. Their release numbers can differ.

The bootstrap variants retain the installed `coinstall-fedora` test. Production
recipes test co-installation with the other Eternal stream instead. Native
rpmx roots include test dependencies, so this split keeps Fedora Go out of the
production root. The C compiler and glibc remain under the existing bootstrap
profile policy.
