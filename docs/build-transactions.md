# RPM build transactions

PR CI starts a transaction through `_start-transaction.yml`. The existing
Commits and Lint checks still run. The old parallel package matrix is no longer
part of PR CI.

The transaction publishes an `RPM transaction` commit status. It stays pending
across worker runs and passes only after the dependency closure settles, all
installed tests pass against the final repository, and the tested candidate is
uploaded. The initial CI run starting successfully does not mean the RPM
transaction has passed. Repository protection should require this status when
this workflow lands.

Each CI continuation dispatch calls `_build-wave.yml` to execute one wave.
Its dynamic package matrix calls `_build-package.yml`, which creates one SRPM and the root locks
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
previous commit. A manual start can select a completed build with `reuse_run`.
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
original transaction, shared source RPM, locks, and checksum-verified CAS
archive. They can rebuild in a fresh cache without contacting repositories or
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
do not have these permissions; this workflow does not use `pull_request_target`
to run fork code with a write token. Fork builds need a separate trusted trigger
or the local adapter.

## Rollout and publication

This draft changes PR execution. Release still calls the previous build path,
in `_build-packages.yml`, so replacing PR scheduling does not change
publication before candidate promotion has been connected and tested. The new
workers do not receive signing or repository credentials. Candidate promotion,
merge-queue freshness checks, and release-path replacement remain rollout work
for this changeset.

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
