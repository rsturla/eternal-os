# Git workflow

This repository keeps a single long-lived branch, `main`, and a linear history.
Every pull request lands as a rebase, so the commits a branch carries are the
commits `main` receives.

## Why linear history

Release identity lives in recipes and in paths, not in branches: a versioned
stream is a directory such as `packages/glibc-2.44/`, and
[`docs/packaging.md`](packaging.md#versioned-package-names-are-streams) explains
why. There is no maintenance branch that a fix has to be merged into twice, so a
merge commit would record a branch topology nobody queries. Keeping history
linear instead buys three concrete things:

- `git log -- packages/glibc-2.44/` shows that package's history without merge
  bubbles or `Merge branch 'main' into …` noise.
- `git bisect` walks a meaningful sequence, because each commit on `main` is one
  package change.
- CI computes the affected packages from a diff against the base
  (`scripts/affected.sh`), so `main` only stays buildable when the tree that was
  tested is the tree that landed.

## Merge policy

The repository settings enforce this; they are not conventions you have to
remember on your own:

| Setting | Value |
| --- | --- |
| Merge commits | disabled |
| Squash merging | disabled |
| Rebase merging | the only allowed method |
| `main`: required linear history | enabled |
| `main`: pull request required, 0 approvals | enabled |
| `main`: force pushes and deletions | disabled |
| `main`: enforcement for administrators | enabled |
| Delete branch after merge | enabled |

Squash merging is disabled on purpose: it would collapse a multi-package pull
request into a single commit and throw away the per-package history this
workflow depends on.

## Working on a branch

```bash
git switch -c packages/core-userland
# … one commit per package, see below …
git fetch origin
git rebase origin/main
git push --force-with-lease
```

Recommended configuration:

```bash
git config --global pull.rebase true
git config --global rebase.autoStash true
git config --global rebase.autosquash true
git config --global rerere.enabled true
git config --global merge.ff only
```

Never merge the base branch into your branch; rebase onto it. A commit that
merges `main` cannot land anyway — the merge would be replayed away — and it
hides which changes the pull request actually introduces.

Review fixes stay as `fixup!` commits while you iterate, then fold them into the
commit they belong to:

```bash
git commit --fixup=<sha of the package commit>
git rebase -i --autosquash origin/main
```

## Commit messages

```text
<scope>: <summary>

<optional body>

many: <reason, only when the commit spans packages>
```

- `scope` is a lowercase identifier naming what changed. Use the package
  directory for a package change (`glibc-2.44`, `gcc-16`, `make`), or one of the
  repository areas: `bootstrap`, `build`, `ci`, `deps`, `docs`, `dx`,
  `metadata`, `release`, `repo`, `scripts`.
- `summary` is imperative, starts in lower case, does not end with a period and
  keeps the whole subject at 72 characters or fewer.
- Traditional Conventional Commits types (`feat:`, `fix(ci):`, `chore:`) are
  not used here: the scope already says what the change belongs to.
- A body, when present, is separated from the subject by one blank line.

Examples taken from the history:

```text
glibc-2.44: add package
make: split development and documentation outputs
dx: hash every graph member before selected closures
```

## One package per commit

Enforced for `packages/`: a commit may change files under at most one
`packages/<name>/` directory. The scope must name that package unless it is one
of the repository areas above.

```text
gcc-16: add the GCC 16 stream          # packages/gcc-16/ only — fine
glibc-2.44: add package                # packages/glibc-2.44/ only — fine
dx: touch glibc-2.44 and gcc-16        # two packages — rejected
```

`bootstrap/recipes/` is deliberately exempt. Adding a bootstrap variant beside
the production recipe is one logical change, and
`packages/foo/package.yaml` plus `bootstrap/recipes/foo/package.yaml` is still a
single `packages/` directory:

```text
bash: add package
    packages/bash/package.yaml
    bootstrap/recipes/bash/package.yaml
```

A change that genuinely spans packages — a repository-wide metadata sweep, a
tool that rewrites many recipes — declares it instead of being split into
commits that would each be meaningless on their own:

```text
metadata: centralize maintainers and identify upstream CPEs

many: repository-wide metadata lives in rpmx-defaults.yaml
```

## Enforcement

The rules live in one script so that local runs and CI agree:

```bash
./scripts/check-commits.sh --base origin/HEAD    # or --range A..B
```

- `make check` runs it against `$(BASE)`, next to pre-commit and
  `scripts/lint-all.sh`.
- A `commit-msg` pre-commit hook validates the message as you write it.
- The `Commits` job in `.github/workflows/ci.yml` checks every commit the pull
  request adds. It runs on pull requests only: `main` is protected, so the
  commits that pass there are the commits that land.

The message check runs locally and in CI; the one-package-per-commit check needs
the commit's diff, so it only runs when a range is inspected.

### Fixing a failure

| Failure | Fix |
| --- | --- |
| `subject is not '<scope>: <summary>'` | `git rebase -i` and reword the subjects |
| `unknown scope` | Use the package directory or a repository area |
| `changes packages/x/ but is scoped 'y'` | Rename the scope to `x`, or reword if the change moved |
| `changes N packages` | Split with `git reset`/`git add -p`, or add the `many:` trailer |
| `merge commit` | `git rebase origin/main` |
| `leftover 'fixup!…'` | `git rebase -i --autosquash origin/main` |

Rewriting a branch means force pushing; use `--force-with-lease` so an
unexpected push is never discarded.
