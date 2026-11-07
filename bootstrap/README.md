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

Bootstrap recipes set `source-date-epoch` to the ladder's value as a fallback
for standalone `rpmx lint`/`rpmx build`; `bootstrap.yaml` owns the effective
timestamp and a stage may override it. Production recipes keep their own value
because a normal `rpmx build` has no ladder manifest to supply one.

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
