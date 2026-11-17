# Package transactions

A release builds from `main` against the published package set. It produces a
complete candidate set, runs acceptance, then publishes those exact bytes.
There is no second build during publication and no persistent side tag.

## Scheduling

`scripts/build-transaction.py` owns the transaction state and rebuild rules.
GitHub workflows transfer artifacts and dispatch native workers. They do not
implement dependency discovery.

1. `init` plans every recipe on both architectures and freezes the published
   Eternal repository metadata. Published RPM locations stay absolute.
2. Recipe hashes are compared with the last successful `build-state.json`.
   Only changed recipes start builds. A failed release never advances these
   hashes, so the next release selects its changes again. The first release
   without a state file selects every recipe.
3. Each package prepares a shared SRPM and separate target dependency locks.
   Its native binary jobs start as soon as its source preparation completes.
   They run build tests before exporting candidates.
4. Changed dependencies build before their consumers. Dependency cycles
   bootstrap together against the published set. `advance` compares candidate public inputs with the published versions.
   It selects consumers that have not built against the changed inputs. A
   consumer built alongside its changed provider must build again in a later
   wave. Generated RPM requirements, declared build requirements, actual root
   inputs and explicit rebuild relationships all contribute dependency edges.
5. `seal` creates the completed candidate repositories. Package acceptance runs
   on native workers against these fixed repositories and the distribution
   runtime profile. Every declared case must pass.
6. Publication verifies source identities, binary checksums, architecture
   completeness and the acceptance repository identity. It publishes the tested
   bytes, retains unchanged published packages, and writes `build-state.json`
   after the repository indexes.

The reusable workflows allow 32 dependency waves. The last wave fails if
consumers still need builds. This is a limit on CI execution, not a successful
partial release. A dependency cycle that keeps changing public inputs needs
an explicit bootstrap policy. The local scheduler has no wave limit unless
`advance --final` is requested.

## What counts as an interface change

An unchanged SONAME does not prove ABI compatibility. The initial detector
compares public shared-library payload digests and SONAME capabilities. It also
compares installed headers and static archives. A change is a possible ABI or
build-interface change and causes consumer rebuilds. This conservative check
can rebuild consumers for compatible changes. RPM release counters, timestamps
and embedded SBOM documents do not count as interface changes.

`rebuild-policy.yaml` records relationships for tools and generated inputs.
For example, the compiler policy package invalidates every recipe when its
installed payload changes. A `'*'` consumer means every recipe. Add explicit
relationships for generators whose effects cannot be found in RPM requirements
or the resolved build root.

Build profiles still control repository exclusions and stream selection. A
candidate that replaces an installed output must be the exact candidate
payload recorded by the transaction. A failed dependency solve or acceptance
stops publication. Adding a package does not silently change bootstrap policy.

## Source identity and build inputs

`rpmx srpm --arch all` assembles sources once. Each matrix cell has one source
RPM shared by x86_64 and aarch64. Target-specific build declarations live in
that source RPM, but resolved dependency closures live in separate `locks/`
files. Architecture-dependent source assembly is rejected.

`scripts/package-artifacts.py prepare` exports the shared sources, target locks
and checksum-verified CAS archives. `rebuild` imports one target's archive and
uses its external lock. It records the exact repository view and consumed
providers. Acceptance is a separate command.

Local repository locks refer to a transaction directory under the rpmx cache.
Source and binary workers use the same cache path and reconstruct that directory
from the same state and candidates. A developer can instead rebuild a published
shared SRPM with `rpmx rebuild FILE --profile PROFILE`, resolving a fresh native
build environment. Exact replay requires the saved target lock and its CAS
payloads. The shared SRPM does not promise to retain an old build environment.

## Storage and cleanup

Candidate RPMs, dependency archives, repository metadata and state use
run-scoped GitHub artifacts with one-day retention. Logs and structured evidence
have seven-day retention. Hosted worker files disappear with their runners.
No temporary repositories or candidate objects are uploaded to R2. Later runs
build their own candidate sets. Run the whole workflow again after temporary
artifacts expire.

R2 receives packages only during final publication. Published objects remain
available to repository clients and the existing archive. Removing published
history is a separate repository policy.

Release workflows run one at a time. A release may follow only a published
commit that is its ancestor. Each architecture's new RPMs and immutable metadata
upload before its index changes. Index changes across architectures are separate
object writes; the completion record advances only after all writes succeed.
A failed upload can therefore require another publication, while each uploaded
architecture index still names a complete tested package set.

## Local commands

The scheduler and worker commands are available outside CI:

```sh
python3 scripts/build-transaction.py init --state .work/transaction/state.json \
  --packages '["zlib"]' --build-release "$(date -u +%s)"
python3 scripts/package-artifacts.py prepare --package zlib \
  --transaction .work/transaction/state.json --candidates .work/candidates \
  --output .work/zlib-source
python3 scripts/package-artifacts.py rebuild --bundle .work/zlib-source/bundle \
  --inputs .work/zlib-source/inputs --arch x86_64 \
  --transaction .work/transaction/state.json --candidates .work/candidates --output out
```

`advance` reads worker artifact directories named
`binary-w<WAVE>-<PACKAGE>-<ARCH>/<PACKAGE>/<ARCH>/`. Both architecture builds
must exist before it can schedule the next wave. `view` reconstructs a fixed
repository from the state and those artifacts. `transaction-artifacts.py`
collects final state and stages accepted outputs for the publisher.
