# Package transactions

A release publishes tested package bytes from a matching pull-request or merge-queue
run. If no candidate matches, it builds on `main` against the published package
set. Signing happens during publication. It changes the RPM envelope while
verification preserves the exact tested main header and compressed payload.
There are no persistent side tags.

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
   bootstrap together against the published set. `advance` compares candidate
   public inputs with the published versions.
   It selects consumers that have not built against the changed inputs. A
   consumer built alongside its changed provider must build again in a later
   wave. Generated RPM requirements, declared build requirements, actual root
   inputs and explicit rebuild relationships all contribute dependency edges.
5. `seal` creates the completed candidate repositories. Package acceptance runs
   on native workers against these fixed repositories and the distribution
   runtime profile. Every declared case must pass.
6. A successful non-publishing run exports a `release-candidate` artifact with
   the accepted bytes, source manifests, repository identity and source tree.
   Publication verifies source identities, binary checksums, architecture
   completeness and the acceptance repository identity. It publishes the tested
   bytes, retains unchanged published packages, and writes `build-state.json`
   after the repository indexes.

The reusable workflows allow 32 dependency waves. The last wave fails if
consumers still need builds. This is a limit on CI execution, not a successful
partial release. A dependency cycle that keeps changing public inputs needs
an explicit bootstrap policy. The local scheduler has no wave limit unless
`advance --final` is requested.

## Reuse after merge

`scripts/promote-packages.py` first finds a successful `merge_group` run for the
merged tree, then a successful PR run for the merged PR head. Manual builds,
failed runs, incomplete acceptance, expired artifacts and other workflows are
ineligible. Queue candidates bind to the exact queue head commit. PR candidates
bind to the PR head or the tested merge commit and its base/head parents. GitHub
commit trees must match the merged checkout, including rebase or squash merges
that change commit IDs.

The release verifies the archive digest supplied by GitHub before extraction.
It then checks the complete artifact inventory, source manifests, target
coverage and acceptance repository identities. Current build-input hashes must
match the tested hashes. The published package baseline must also match, and
the PR must cover every recipe required by current published hashes. That last
check prevents reuse from overlooking changes from an earlier failed release.
Direct PR promotion requires a newer release counter than the published counter.
A queue can validate an older PR counter after an unrelated publication. It must
first prove that no published source family replaced by that PR has changed.
The publication watermark stays monotonic without changing the tested RPMs.

A missing or mismatched candidate falls back to the normal main transaction.
A failure during signing or publication fails the release instead of starting
a second publisher. Only the gated main publication step receives signing and
bucket credentials. PR and queue builds have neither credential.

Both reused and freshly built packages use `publish-packages.sh`. It signs RPMs
and rejects any change to their main headers or compressed payloads. The
`signing.json` receipt maps original tested file digests to signed file digests.
Source manifests retain their tested envelope identities. `promotion.json`
records the source run and merged commit for reused packages. These receipts
have seven-day artifact retention. Repository metadata uses the final signed
file digests.

### Merge queue checks

CI handles `merge_group: checks_requested` and reports a stable `Required CI`
check. `_check-queue.yml` imports the successful PR run's existing RPMs. It never
compiles packages. `scripts/queue-packages.py` verifies the GitHub archive digest,
completed run, exact PR head, source manifests and original acceptance records.

The queue checks the following conditions before it runs acceptance:

- The integrated tree is exactly current `main` plus one open PR. A tree check
  rejects larger groups or a different PR head.
- Every reused package has the same build-input hash as the integrated tree.
  Unrelated recipe and documentation changes on `main` do not require recompilation.
- Published hashes cover every other recipe on latest `main`. If a previous
  release failed or is still in progress, the queue requires publication first.
- The PR's replaced source families have not changed in the published baseline.
  Each PR RPM must also have a newer epoch, version and release than its published
  counterpart. This prevents replacement of newer RPMs by older PR artifacts.
- Changed dependencies retain their public build inputs. The queue checks
  declared dependencies, actual consumed build-root providers and tool policy.
  The complete PR rebuild set must still cover all required consumers.

The queue overlays the exact PR RPMs on a fresh published `main` snapshot.
Native acceptance runs against this fixed combined repository on both
architectures. A successful run exports the same RPM bytes in a new candidate.
Its records bind the acceptance result to the queue tree and original PR run.
After merge, the release prefers this candidate and signs and publishes its RPMs.

Missing or expired PR artifacts block the queue. Changed build inputs or an
incomplete rebuild set require an updated PR and a new PR build. The queue does
not hide these failures by rebuilding. Documentation-only PRs need no package
artifact. Commit conventions run on PR commits, while lint runs on the integrated
queue tree. `Required CI` requires the applicable PR or queue workflow to succeed.

After this workflow lands on `main`, branch protection can require `Required CI`
and enable the merge queue. Use rebase merges to retain linear history. Set
queue build concurrency and maximum merge group size to one. Allow enough check
timeout for native acceptance. An unexpected combined group fails the tree check.
Existing protection rules must be reconciled when enabling the queue. This
changeset does not enable a queue before its workflow exists on the base branch.

A queue allows the source tree to advance without recompilation when the PR's
build inputs remain valid. A repository publication during queue testing can
still invalidate the candidate. That release takes the safe rebuild path.

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
No temporary repositories or candidate objects are uploaded to R2. A merged
release can reuse a matching unexpired candidate. Other runs build their own
sets. Run the whole workflow again after temporary artifacts expire.

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
