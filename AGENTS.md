# Eternal OS agent notes

This repository builds Eternal Linux: RPM recipes in `packages/`, bootstrap
variants in `bootstrap/recipes/`, and rpmx as the build tool.

## Read this first

- **Packaging rules:** [`docs/packaging.md`](docs/packaging.md) — versioned
  streams, subpackage splits, dependencies, licensing, tests and review
  checklist. Follow it for every recipe change.
- **Adding a package:** [`docs/adding-a-package.md`](docs/adding-a-package.md)
- **Architecture:** [`docs/architecture.md`](docs/architecture.md)
- **Git workflow:** [`docs/git-workflow.md`](docs/git-workflow.md) — linear
  history, rebase merges, commit message and one-package-per-commit rules.
- **Signing:** [`docs/signing.md`](docs/signing.md)

## Working rules

- Never commit directly to `main`. Work on a branch and open a pull request.
  Pull requests land as a rebase, never as a merge commit or a squash; see
  [`docs/git-workflow.md`](docs/git-workflow.md).
- Rebase onto `main` instead of merging it into your branch.
- One commit carries one package change: a commit may touch files under at most
  one `packages/<name>/` directory, and its `scope:` names that package. Use
  `many: <reason>` trailer only for changes that genuinely span packages.
  `bootstrap/recipes/` does not count towards the limit.
- Commit subjects are `<scope>: <imperative summary>`, lower case, without a
  trailing period, with a package name or a repository area as the scope.
- `packages/<name>/package.yaml` is the rolling production recipe.
  `bootstrap/recipes/<name>/package.yaml` is the bootstrap-only variant of the
  same package; keep both when the package participates in the ladder, and do
  not move a package between the two.
- Keep bootstrap stage policy in `bootstrap/bootstrap.yaml`; recipes do not
  contain seed or stage logic.
- Repository-wide metadata belongs in `rpmx-defaults.yaml`, not in every
  recipe.
- Do not add CI-only build logic. Workflows call `scripts/`; local and CI use
  the same entry points.
- Validate recipe changes with `rpmx lint` (or `./scripts/lint-all.sh`) before
  proposing a commit, and `./scripts/check-commits.sh` before pushing.
- The pinned rpmx revision is `.rpmx-revision`. Do not bump it incidentally.
