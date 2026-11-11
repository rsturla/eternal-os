# Upstream release tooling design

Status: proposed. Investigated on 2026-11-11. Commands and configuration below
describe the intended interface unless explicitly marked as existing.

## Recommendation

Use rpmx for recipe updates and source preparation. Keep Eternal's package
selection, stream policy, bootstrap coupling and pull requests in this repository.
Reuse upstream-monitor for release discovery, subject to the provider work below.
All three must run locally. A hosted catalog, message broker and GitHub Actions
must be optional.

Start with a local `scripts/upstream` command that requires one package per run.
It consumes release observations,
creates a deterministic update plan, validates the changed recipe and publishes
a pull request. A separate `scripts/upstream-all` meta-script enumerates packages
and invokes workers every two minutes. The worker never scans other packages.
Do not put GitHub credentials, polling or Eternal policy into rpmx.

Keep package-specific update configuration beside the build definition in
`package.yaml`, under `metadata.eternal.update`. Add an opaque `metadata` map to
rpmx's recipe schema. Eternal owns validation and interpretation of its namespace.

The target is a reviewable PR within 15 minutes of an upstream release. Full
builds can continue after publication. A PR with incomplete or failed preparation
must remain a draft and state the failure. Count these separately from successful
updates; an empty notification PR does not meet the target.

## What exists today

The checkout contains 116 production recipes and six bootstrap recipes:

| Recipe shape | Count | Consequence |
| --- | ---: | --- |
| Archive sources | 108 | Resolve the official artifact, update its locators and recompute its digest |
| Pinned git sources | 2 | Both glibc streams need deterministic git archive digests |
| No downloaded source | 6 | Explicitly opt out of upstream tracking |
| Recipes with patches | 9 | Check patches against the new source |
| Recipes with multiple sources | 1 | pip has four independently versioned inputs |

These rows overlap. The six local recipes are `basesystem`, `eternal-base`,
`eternal-baselayout`, `eternal-release`, `filesystem` and
`openssf-compiler-options`. The last recipe currently has no downloaded source;
future tracking of its vendored material needs a separate policy.

There is no existing release watcher in Eternal's workflows. PR CI already
checks commit conventions, lints recipes and builds affected packages. Reuse it.
Package locks are currently gitignored because bootstrap roots float. Update PRs
must not start committing locks or change `.rpmx-revision` incidentally.

The pinned rpmx revision is `568baf3573a7da76208bf19a9d6d8c2a6f87b944`.
Its existing `bump` command changes the version and literal versions in source
URLs. It does not reset the release, update source names, resolve transformed
tags, handle PyPI content paths or update version assertions. More seriously,
digest refresh receives the original source definitions after rewriting the
text. This can pair a new URL with an old digest. Fix and regression-test this
before unattended use. See the pinned
[implementation](https://github.com/rsturla/rpmx/blob/568baf3573a7da76208bf19a9d6d8c2a6f87b944/crates/rpmx-cli/src/commands/bump.rs).

[rpmx PR #50](https://github.com/rsturla/rpmx/pull/50) fixes digest acquisition
and the release reset. Its local validation passed 105 relevant tests, formatting
and workspace-wide Clippy checks. Eternal's pin remains unchanged until an
explicit dependency update adopts the fix.

`rpmx fetch`, `rpmx source`, `rpmx lint`, `rpmx plan` and `rpmx build` already
exist. Source assembly materializes sources, copies context, applies patches,
then runs `source-assembly` steps. The current Eternal recipes have no explicit
`source-assembly:` section. Some preparation happens inside `build.pipeline`,
including pip's vendor replacements. Tracking must cover both forms.

## Ownership and alternatives

| Module | Owns | Excludes |
| --- | --- | --- |
| Release discovery | Provider queries, normalized versions, publication evidence, stream classification, conditional requests | RPM recipes and PRs |
| rpmx recipe update | Schema-aware edits, opaque metadata preservation, source acquisition and digests, release policy mechanics, source preparation, machine-readable results | Interpretation of Eternal metadata, stream choices and GitHub state |
| Eternal update coordinator | Recipe-local update configuration, related bootstrap recipes, retries, branches, PRs and latency records | Duplicate implementations of rpmx fetching or assembly |

The seams are a release observation and a recipe update plan. Local files and a
remote catalog are adapters at the discovery seam. A CLI caller needs no knowledge
of polling storage, provider caches or GitHub event delivery.

A local checkout of `rsturla/upstream-monitor`, inspected at
`5055bdd27c21682cd890fa08585b979032f316e9`, already provides local validation,
network dry-runs, file-backed polling, stream filtering and optional durable events.
Its documented providers include Git tags, GitHub Releases, GitLab releases and
GitLab tags. Do not assume it covers PyPI, GNU directory listings, numbered Bash
patches or Mozilla Mercurial tags. These need providers or verified equivalent
release feeds. Its default timeouts and scheduler settings also need adjustment
and measurement for this target. No changes to that checkout are part of this
design.

Reuse that project through a versioned executable and JSON contract, not a
cross-repository import of its Go `internal` packages. Add a one-shot, persisted
check interface there if needed. Its existing `dry-run --project` discovers
without persistence and is useful for local inspection. The coordinator derives
monitor project definitions from recipe metadata for the requested package.
These definitions are generated inputs, not a second hand-maintained package
catalog. Production must reconcile
catalog state as well as consume events: the first monitor poll establishes a
baseline and does not emit the existing release history.

Renovate is a credible alternative for discovery and GitHub PR management.
Its [custom managers](https://docs.renovatebot.com/modules/manager/regex/) can
extract versions, and a self-hosted installation can run approved update commands.
Eternal would still need rpmx update logic for digests, patch sets and assembly.
Prefer the existing monitor plus a small coordinator here. Reconsider Renovate
if the maintenance cost of PR lifecycle handling becomes larger than expected.
Anitya can supply additional release evidence, but its public detection latency
must not be assumed to meet Eternal's target.

## Local interface

The proposed command runs from any checkout with an explicit repository path.
It uses the same implementation interactively, from a timer and from CI:

```sh
./scripts/upstream-all audit
./scripts/upstream check --package zstd --output /tmp/releases.json
./scripts/upstream plan --observations /tmp/releases.json --output /tmp/update.json
./scripts/upstream apply --plan /tmp/update.json --work-dir /tmp/eternal-update
./scripts/upstream verify --work-dir /tmp/eternal-update
./scripts/upstream publish --work-dir /tmp/eternal-update
./scripts/upstream run --package zstd
./scripts/upstream-all run --jobs 1
./scripts/upstream-all run --jobs 8
```

The meta-script's `audit` validates that every production recipe has enabled
update metadata or an explicit opt-out reason. It also reports unsupported
resolvers and stale checks.
`check` is read-only with respect to Git. It needs network access, but no GitHub
write token. `plan` can replay recorded observations offline. `apply` writes into
a separate checkout and never changes the caller's working files. `verify` uses
rpmx and the repository scripts. `publish` is the only phase that needs repository
write credentials. `run --package NAME` composes these commands for exactly one
package and exits. Later phases recover the package identity from the plan and
reject mismatches. A paired bootstrap recipe remains part of that one package.

Only `upstream-all` discovers package names, excludes explicit opt-outs, controls
worker concurrency and aggregates results. It invokes the worker executable once
per package, with separate output and work directories. It must not duplicate
resolver, comparison, retry or publication logic. A timer invokes the meta-script;
a distributed queue can later invoke the same workers directly.

Each worker emits one versioned JSON result with package, outcome, phase,
retryability, timestamps, plan path and optional PR URL. Outcomes distinguish
`unchanged`, `updated`, `blocked`, `unsupported` and `failed`. Use exit code 0 for
completed checks, including unchanged results, 1 for failed checks and 2 for
invalid invocation. Detailed outcomes live in JSON. The meta-script waits for all
workers, preserves every result and exits nonzero if any required check fails.
Use per-package leases and atomic state writes. Share only a coordinated provider
cache or immutable content-addressed artifacts; never share mutable work files.
Host-wide quotas must still apply when workers run concurrently. A per-package
invocation can query a shared upstream project's feed, but selects and modifies
only the requested package.

Use the repository's pinned rpmx binary. Document host dependencies through the
existing setup scripts and `rpmx doctor`. Source preparation needs a usable build
root and runner, just as a normal local build does. Allow an explicit state/cache
directory under XDG defaults. File-backed state needs no database or broker.
Offline replay requires cached source bytes and prepared roots as well as JSON.

The plan records a schema version, base Git SHA, effective update configuration
hash, recipe hashes,
upstream project/stream, raw tag, normalized version, timestamps, artifact URLs,
immutable commit IDs, expected checksums, intended field edits and check results.
Reject changed inputs before apply or publish. Do not evaluate release text as
shell code. Pass command arguments as arrays.

## Configuration

Store each package's upstream identity, version constraints, artifact selection
and preparation rules in its recipe under `metadata.eternal.update`. Keep these
rules beside the sources and build steps they describe. There is no separate
hand-maintained `upstream/packages/` or `upstream/projects/` configuration tree.
Do not use `package.upstream` as a download endpoint.

The proposed recipe extension is a generic, optional `metadata` map. rpmx accepts
and preserves this map without interpreting downstream namespaces or expanding
their template strings. Normal recipe validation remains strict outside it.
Eternal's tooling validates `metadata.eternal.update`, including its schema
version, required fields, unknown fields and provider-specific settings. Other
tools can use their own namespaces without changes to rpmx.

The pinned rpmx recipe schema currently rejects this field. Add support through
a separate reviewed rpmx change before enabling recipe annotations. That change
must cover recipe fragments, includes, serialization and recipe bundle handling.
Metadata must survive bump operations, locks and SRPM round-trips. It must not
introduce build steps or recipe variables. A typed rpmx `update:` section can be
considered later if multiple downstream tools agree on shared semantics.

An illustrative block inside `packages/zstd/package.yaml`, with downstream syntax
to finalize during implementation:

```yaml
metadata:
  eternal:
    update:
      schema: 1
      enabled: true
      upstream:
        provider: github-releases
        repository: facebook/zstd
      version:
        strip-prefix: v
        prereleases: false
      preparation:
        resolver: github-release-asset
        sources:
          - name: zstd-${package.version}.tar.gz
            asset: zstd-${version}.tar.gz
```

In this namespace, Eternal resolves `${package.version}` from the current recipe
and `${version}` from the selected release. rpmx preserves these strings verbatim.
Versioned packages also declare a stream constraint, such as `stream: "16"`
for `gcc-16`. A local package instead declares `schema: 1`, `enabled: false`
and a nonempty `reason` in the same namespace. Missing metadata is an audit
failure, not an implicit opt-out.

Keep repository-wide defaults in `rpmx-defaults.yaml`. Eternal can read shared
version policy from `metadata.eternal.update` there. Its coordinator merges those
defaults with the recipe's update metadata. Recipe values take precedence;
mappings merge recursively and lists replace inherited lists. Each production
recipe must still declare its enabled status and upstream identity or opt-out.
Record the effective configuration and the contributing file hashes in the plan.
This inheritance is Eternal tooling behavior, not implicit rpmx interpretation.

Store polling, concurrency, PR settings and explicit bootstrap pairing under
`metadata.eternal.upstream` in `rpmx-defaults.yaml`. Use environment variables or
local credential references for secrets. Runtime observations, generated monitor
definitions and work state belong in the configured state directory.

Update metadata identifies sources by existing names or checked selectors.
Do not assume the first source is the only one. Add stable source identifiers to
rpmx only through an intentional schema change if mutable names become a problem.
Resolvers produce exact field edits. Prefer upstream release metadata over
guessing transformed URLs. Use declarative transforms for routine tag spelling.
Use reviewed resolver code for SQLite encoding and numbered patch sets.

Every stream has an explicit range. GCC 13 through 16 and Python 3.11 through
3.15 remain separate. The glibc, Perl, Lua and OpenSSL recipes also need their
own stream rules. A new stream produces an actionable discovery record; it does
not rename packages, add selectors or rewrite dependencies automatically.
Reject prereleases unless a recipe explicitly opts in.

Bootstrap pairing is explicit in the repository configuration. Bash, binutils,
coreutils and make can update both recipe variants in one package commit after
validation of each.
Keep bootstrap roots, epochs and build differences. The two local bootstrap
recipes remain opted out. Never move stage logic out of `bootstrap/bootstrap.yaml`.
The worker reads update policy from the production recipe and applies the
repository's explicit pairing. Bootstrap recipes do not need duplicate upstream
discovery metadata.

## Update semantics and source preparation

For a higher upstream version, set `package.version` and reset the recipe's
`package.release` to `1`. Preserve the epoch. Keep generated matrix release
suffixes and release-run `+build<timestamp>` handling under their current owners.
For a new source commit or a vendored dependency at the same package version,
increment the packaging release. Do not reset it or invent a patch version.
Reject an unrecognized release format rather than guessing its next value.

| Family or example | Discovery and update behavior |
| --- | --- |
| GNU archives, GCC and binutils | Poll the canonical release listing, select the allowed stream, resolve release artifacts and mirrors |
| GitHub projects | Use Releases when that is upstream's release authority; use tags only when configured; prefer published tarballs to generated archives |
| Python modules | Query PyPI, select a non-yanked sdist, use its exact content URL, check published hashes and record upload time |
| CPython, Perl, Lua, OpenSSL | Bind each stream to its official release feed and artifact layout |
| SQLite | Resolve the release year and upstream numeric archive encoding; neither follows literal version replacement |
| tzdata | Compare year/letter versions; select a coherent archive layout; a GitHub tree and IANA data tarball are not automatically byte-identical mirrors |
| ca-certificates | Track NSS release tags and resolve the matching certdata file through Mercurial metadata |
| Bash | Discover numbered upstream patches, retain the base tarball, vendor the complete contiguous patch chain and update patch-level assertions |
| Readline | Decide explicitly whether numbered patches define packaged patch versions; never assume a new tarball exists |
| glibc-2.43 and glibc-2.44 | Track their documented stable branches as source refreshes, pin a full commit and regenerate the rpmx deterministic archive digest |
| python-pip | Track pip and each vendored source independently; re-evaluate vendor replacement commands and bundled metadata |
| Other patched recipes | Retain local patches and test them; require review for conflicts or removal |

Do not claim coverage from recognizing an upstream host alone. During rollout,
`audit` must enumerate all 116 recipes and link each enabled update configuration
to a passing resolver fixture. Source families above are design coverage, not
implemented resolvers.

The rpmx update implementation must first resolve edits into a candidate recipe,
then fetch from that candidate, then write the computed digests. Preserve comments
and unrelated fields. Match sources structurally rather than by digest-line
position. Validate the entire recipe bundle before publishing any file changes.
Included recipe files require a staged transaction, not independent writes that
leave half an update after failure. A dry-run downloads when necessary to compute
the actual diff, but writes no recipe files. `--no-fetch` cannot yield a verified PR.

Keep package-specific prep changes explicit. Bind known version assertions and
version-dependent paths to checked edits with expected old values. Do not replace
every old version in shell blocks. Do not let an agent silently rewrite build
commands, remove patches or change build dependencies. Unsupported preparation
changes produce a draft with the exact failing command and retained evidence.

Run `rpmx fetch`, `rpmx lint`, `rpmx plan` and `rpmx source` on the candidate.
Source verification must use the same root, patches and assembly implementation
as an actual build. Until pip's prep moves to source assembly through a separate
reviewed change, `rpmx source` alone does not validate its vendor replacements.
Run a build for this case, or report preparation as incomplete.
Validate all declared target architectures and matrix-dependent prep. A first
architecture result must not claim complete coverage of the others.

Only call locators mirrors when they identify identical bytes. Compute SHA-512
from the downloaded artifact. Also verify upstream checksums or signatures where
available, using reviewed trust configuration. Hashing an arbitrary response only
pins bytes; it does not authenticate the publisher. Retry lagging mirrors without
blocking an available canonical artifact; report missing mirror verification.
Never accept a changed digest at the same immutable URL/tag as an ordinary update.

## Latency and execution

Use a continuously running local process or a systemd timer with persistent state.
The unattended host can be a workstation or a dedicated machine. GitHub's
[schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
allows delays and dropped jobs, so Actions cron cannot provide this latency target.
An external timer that merely dispatches a queued Actions job still has queue risk.

Budget the 15 minutes as an engineering target:

| Phase | Budget |
| --- | ---: |
| Publication visibility and polling | 2 minutes |
| Queue and artifact resolution | 1 minute |
| Fetch, rewrite and preparation | 8 minutes |
| Lint, commit and PR publication | 2 minutes |
| Retry margin | 2 minutes |

These are proposed budgets, not measured performance. Poll every two minutes
with bounded jitter included in that interval. Use bounded parallel checks,
conditional requests and per-host quotas. Keep prepared roots and rpmx binaries
warm; do not compile rpmx in every polling cycle. Isolate slow packages so a
large GCC download cannot block small updates. Measure a simultaneous release
burst before selecting worker and bandwidth limits.

Record upstream publication time, first observation, artifact readiness,
preparation completion and PR creation. Target p95 under 15 minutes and report
every breach. Missing or unreliable publication timestamps must remain unknown;
also report observation-to-PR latency. Track coverage, last successful poll,
queue age, draft failures and successful prepared PRs separately.

Artifacts sometimes appear after the announcement. Poll them again with bounded
backoff. Include that delay in release-to-PR reporting. Do not reset the clock at
artifact readiness. No tool can guarantee a prepared PR while upstream artifacts
or GitHub are unavailable. Report these cases as misses with evidence.

## PR lifecycle and unattended execution

Use one PR and one package commit per recipe update, including explicitly paired
bootstrap variants. Use a deterministic branch under `codex/`, keyed by package,
target version and source revision. Commit subjects follow
[`git-workflow.md`](git-workflow.md), for example `zstd: update to 1.5.8`.
Run `scripts/check-commits.sh` before pushing and `scripts/lint-all.sh` before
publication. Do not merge automatically.

Persist work states from observation through plan, apply, verification and
publication. Recover after a crash by checking GitHub for the exact branch and
plan identity before creating another PR. Hold a local lock per package;
distributed execution needs a real shared lease store. File state is sufficient
for the initial single-host deployment. A failed package must not stop a batch.

Newer releases supersede pending work through an explicit status transition.
Do not rewrite branches with human commits. Rebase bot-only branches onto current
main and repeat checks. Use force-with-lease when updating them. A closed PR
records a suppression for that target unless a maintainer explicitly retries it.
Recover missed events by comparing current recipes with the latest observations
on startup and at least every two minutes.

A PR body includes release evidence, old/new version and release, source/digest
changes, bootstrap changes, prep checks and outstanding build results. Source
preparation failures or skipped required checks produce a draft. Successful prep
can produce a normal PR while full builds run through existing PR CI.

Use a repository-scoped GitHub App token for unattended publication. Local users
can use their existing GitHub authentication. Follow GitHub's documented
[workflow token behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
and verify that bot PRs start existing CI without manual intervention. Keep write
credentials out of the source-preparation runner. The publisher consumes a
validated diff and manifest from the trusted base checkout; it does not execute
code supplied by an upstream release or a generated branch.

## Delivery and acceptance

1. Repair existing rpmx bump behavior in a focused upstream PR. Test new-byte
   digest refresh, release reset, failed fetch rollback and dry-run behavior.
   Adopt a reviewed rpmx revision later in an explicit dependency update.
2. Add opaque recipe `metadata` support in a separate rpmx PR. Validate its
   preservation through includes, serialization, bump operations, locks and SRPMs.
   Adopt the schema support through an explicit rpmx dependency update.
3. Add the coordinator's offline plan/apply interface, state transitions and
   recipe metadata validation. Add an exhaustive configuration audit and defaults
   inheritance. Keep GitHub writes behind `publish`.
4. Integrate monitor observations and add missing discovery providers. Start
   with ordinary GNU/GitHub archives and PyPI modules. Replay saved upstream
   responses through the same resolver interfaces used by polling.
5. Add Bash, glibc, SQLite, NSS, tzdata and pip fixtures before enabling their
   update metadata. Add explicit stream policies and bootstrap pair checks.
6. Run without publication, then enable PRs for a small package set. Measure
   latency, rate limits and burst handling before enabling the full inventory.

Acceptance tests must demonstrate a release becoming a changed recipe with
fresh digests and the correct release value. Check namespace preservation,
downstream schema errors, explicit opt-outs, defaults precedence and stale
configuration hashes. Verify that a worker reads only the requested package's
update configuration and repository defaults. Cover transformed tags, opaque PyPI
URLs, independent pip dependencies, a missing Bash patch, a glibc commit refresh,
an upstream repack, a mirror mismatch, patch conflicts and source assembly errors.
Also cover stale plans, no-op retries, duplicate events, a crash after push,
closed PR suppression, a human-edited branch and a newer release during work.

The complete flow must run locally with file state, fixture HTTP responses and
a fake publisher. A network-backed local run must exercise the same commands.
Live PR publication then verifies GitHub permissions and CI triggering. Scheduled
execution adds process supervision and credentials, with no extra update logic.
