# RPM build transactions

PR CI starts a transaction through `_start-transaction.yml`. The existing
Commits and Lint checks still run. The old parallel package matrix is no longer
part of PR CI.

The transaction publishes an `RPM transaction` commit status. It stays pending
across worker runs and passes only after the dependency closure settles, all
installed tests pass against the final repository, and the tested candidate is
uploaded. The initial CI run starting successfully does not mean the RPM
transaction has passed. Repository protection requires this status and `RPM freshness`, with up-to-date branches.

Each CI continuation dispatch calls `_build-wave.yml` to execute one wave.
Its dynamic package matrix calls `_build-package.yml`, which creates one SRPM and complete input records
for both architectures. That package then calls `_build-rpm.yml` on native
runners. Packages do not wait for other packages' SRPMs before starting their
binary builds.

All packages in a wave consume the same fixed repository view. Once they
finish, `build-transaction.py advance` checks their bytes and records their
public interfaces and consumed providers. It selects the next ready packages.
Build ordering and rebuild detection both apply the root profile's repository
filters when matching providers. A compiler stream excluded from the root cannot
trigger rebuilds just because it advertises the same library capabilities as the
selected compiler. Recorded inputs and explicit rebuild policy still trigger
rebuilds. Runtime requirements can trigger a rebuild, but do not add build-order
edges. Seed-only roots do not wait for candidates they cannot consume. These
inputs come from existing recipes and profiles.
A continuation dispatch starts the next wave. Each run has its own job time
limits; there is no long-running job waiting for the entire transaction.
The transaction fails if its closure has not settled after 32 waves.

Source acquisition retries network failures up to three times, with 15- and
45-second delays. This wraps rpmx's own fetch attempts and uses its diagnostic
codes. Digest mismatches, recipe errors, and local storage errors stop
immediately. Assembly, compilation, and tests are not retried. The same source
command runs locally and in Actions.

Published RPM and build-state downloads use the same bounded backoff for
connection failures, short responses and temporary HTTP errors. A downloaded
RPM enters the comparison cache only after its full checksum matches. Permanent
HTTP errors, checksum mismatches and local storage errors stop immediately.

Dispatched run names include the originating PR number, which stays in the
GitHub adapter's context.

Static-archive comparisons ignore archive member timestamps and owners. They
retain member names, order, modes, symbol indexes, and object bytes. RPM and
artifact checksums still cover the exact published bytes. This prevents an
archive-index timestamp from causing another rebuild wave.

When no builds remain, the planner seals the final repository. A final dispatch
runs installed tests in batches of four packages on each architecture. It exports one
`release-candidate` artifact after every acceptance job succeeds. This artifact
expires after 14 days. Intermediate artifacts expire after seven days.

## Execution adapters

`build-transaction.py`, `package-artifacts.py`, and `transaction-artifacts.py`
contain the shared planning, build, validation, and export operations. Their
state and artifact formats have no GitHub identifiers.

`build-waves.py` is the local execution adapter. It runs a wave, advances the
planner, and repeats. It accepts the final repository and exports a candidate.

`actions-build.py` is the GitHub transport adapter. The workflows execute the
same operations and resume from uploaded snapshots. A separate `context.json`
records the source ref, originating workflow run, and each completed wave's run.
The adapter downloads the precise artifact generations the planner selected,
checks archive hashes, and reports the aggregate commit status. It refuses to
continue after the source branch moves. A new PR commit starts a new transaction.

On a PR update, the adapter looks for a settled candidate snapshot from the
previous commit. A new PR can reuse a settled snapshot whose tree exactly matches
its merged main base. The adapter discovers that snapshot through the merged PR. A manual start can select a completed build with `reuse_run`.
The shared `build-transaction.py reuse` operation verifies the old commit/tree,
baseline metadata, binary inventories and checksums. It compares tracked recipe,
context, profile, defaults, compiler-policy, rpmx and execution-script inputs.
Repository assembly and interface comparison code remain inputs; scheduling,
transport and export changes alone do not require recompilation. Changed or new
inputs enter the normal rebuild closure. Old candidates remain available as
bootstrap inputs until their replacements build. Original SRPMs, locks, source
records and consumed-provider views remain unchanged for retained builds.

Reused transactions keep their artifact generation numbers and receive a fresh
32-wave budget. Every package runs acceptance against the new sealed repository
on the new commit. Earlier acceptance results cannot satisfy that gate. Changes
to rebuild policy or provenance requirements require a fresh start. The local
adapter can use the same reuse operation with local snapshot and artifact paths.

Source workers download one pool containing the latest canonical candidate
RPMs. The coordinator creates that pool after it validates a wave; old
iterations and build evidence do not enter it. Binary workers receive the
original transaction, shared source RPM, complete input records, and
checksum-verified CAS archive. Each record pins the build root, sysroot, and
source-test environments. Its payload inventory includes test-only dependencies. They can rebuild in a fresh cache without contacting repositories or
downloading previous waves. The pinned rpmx executable uses the shared setup
cache on each architecture.

The final acceptance snapshot contains the sealed repository, transaction,
latest source bundles, and binary pool. Each acceptance batch downloads that
snapshot once. Source-artifact listings are shared per producer run when the
coordinator assembles it. These transfers keep API use proportional to jobs
rather than packages multiplied by all preceding candidates.

An external service can replace this transport and dispatch mechanism while
keeping the shared operations, snapshots, and package workers. It does not
need to interpret GitHub job outputs to calculate dependencies.

The dispatcher needs Actions and commit-status write permission. Fork PR tokens
cannot dispatch workers. Fork PRs still run lint, commit and freshness checks.
A maintainer can mirror an explicitly reviewed fork SHA into the main repository:

```console
GITHUB_REPOSITORY=rsturla/eternal-os python3 scripts/actions-build.py import-pr \
  --number 123 --sha <reviewed-40-character-head-sha>
```

The command creates a branch without checking out or executing fork code. It
prints the manual CI command, including the original PR number. A moved fork
head requires a new review SHA. Workers receive no signing or repository keys.
The local adapter remains available for builds without GitHub dispatch.

## Publication

`release.yml` promotes the accepted candidate from the merged PR. It does not
call the old parallel build matrix. Rebase merges change commit IDs, so the
adapter compares Git trees and locates the original PR head's successful CI run.
The shared `transaction-artifacts.py release` command verifies the candidate
inventory, RPM checksums, source manifests and final acceptance repository on
every production architecture. It rejects a different tree or rpmx revision.

Release preparation retains unchanged published binary and source RPMs. It
rejects changed baseline packages outside the candidate's replaced source
families. It then signs RPMs without recompilation. The publisher uploads RPMs
before metadata indexes and writes `rolling/build-state.json` last. The build
state records the merged commit, original candidate commit and recipe hashes.
Only one release can publish at a time. A release stops if main has moved before
publication. Signing and storage credentials exist only in the release job.

For a retry on main, `workflow_dispatch` accepts an optional `candidate_run`.
The same tree, acceptance and baseline checks apply. Missing or expired candidates
fail instead of rebuilding implicitly. A successful transaction with no RPM
changes skips publication. Candidate retention remains 14 days; intermediate
snapshots expire after seven days. These transaction artifacts need no R2 side
repositories or R2 cleanup tasks.

## Merge freshness

`RPM freshness` requires the PR head to contain the current base commit. Rebase
an outdated branch and rerun CI. The planner can reuse unchanged build inputs,
but all retained packages run acceptance against the refreshed final repository.
Require `Commits`, `Lint / Lint`, `RPM transaction` and `RPM freshness`, with strict
up-to-date checks in branch protection.

The freshness workflow also handles `merge_group`. It requires a successful
candidate whose tree exactly matches the merge group's tree, including current
main. Configure one PR per merge group when a merge queue becomes available.
A changed group tree requires refreshed PR CI; it cannot pass with stale artifacts.
GitHub merge queues currently require an organisation-owned repository, so this
personally owned repository uses strict branch protection instead.

## OpenSSL bootstrap follow-up

OpenSSL retains its upstream `COMP_*` entry points for consumers built against
Fedora headers. Its zlib, zstd and Brotli compression backends stay disabled.
Removing those entry points with `no-comp` is a separate bootstrap transition.
Build Python and other consumers against Eternal's `no-comp` headers, replace
seed tools that still require the APIs, and accept the complete candidate
repository before publication. Rebuilding against the compatibility headers
continues to permit references to those APIs.

## Tests

`test-build-waves.yml` builds real A → B → C → D fixtures natively on both
architectures. It verifies exact preceding-wave lock checksums, final installed
behavior, unchanged interfaces, deliberate build and acceptance failures, the wave limit, and a binary rebuild in a fresh cache with no coordinator
repository or candidate directories. See [the fixture instructions](../tests/fixtures/build-waves/README.md).

`test_actions_build.py` checks artifact corruption, archive traversal, wave-to-run
selection, and source-branch movement at the GitHub boundary. Those checks are
separate from the native RPM tests so other adapters can reuse the latter.

## Input availability and new dependency chains

A transaction can introduce a provider and its consumers in the same merge
request. Planned recipe capabilities define dependency order. They do not prove
that an RPM is available for a build.

Before dispatch, the planner builds one repository snapshot and runs `rpmx
inputs` for each eligible recipe on every target architecture. This resolves the
same build, sysroot and enabled source-test inputs as source preparation, with
the same profile and repository exclusions. Only recipes that resolve on all
targets enter the wave. Candidates from that wave become available in the next
snapshot.

For example, a new B builds before A when A requires B. Within a dependency
cycle, published RPMs can supply compatible inputs. If a new stream is missing,
its consumers wait while a resolvable cycle member builds first. Existing input
fingerprints still drive further rebuilds after provider interfaces change.

Readiness reports are kept under the transaction's `readiness/` directory.
Unsatisfied dependencies defer a recipe. Network, authentication, invalid recipe
and other resolution failures stop planning. If packages remain but none can
resolve, the planner reports blocked providers and target diagnostics. Supply a
compatible seed or an explicit bootstrap stage to break such a cycle.
