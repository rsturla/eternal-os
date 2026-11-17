# Build-input provenance and consumer rebuilds

Status: proposed. This document defines a design for review, not current behavior.
It changes no recipes, RPM metadata, build commands or repository settings.

## Problem

A package can contain vulnerable code without a runtime dependency on its
provider. Go standard libraries, Rust crates, static libraries and C++ templates
are examples. Updating the provider does not replace code already incorporated
into another RPM.

Compilers and generators create a second relationship. A compiler can emit
incorrect machine code without contributing a library to the result. A fix can
require rebuilding its outputs even when their source and runtime ABI stay the
same. Runtime acceptance tests cannot prove that all such defects are absent.

We need to answer two questions from published package metadata:

1. Which source recipes produced RPMs affected by this component or tool update?
2. Did their replacement RPMs use the repaired inputs?

The answer must remain available after temporary CI artifacts expire.

## Goals and scope

- Implement a general input-to-output relationship model before toolchain integrations.
- Record incorporated components and build tools separately from runtime dependencies.
- Select consumer rebuilds across language toolchains and native libraries.
- Distinguish toolchain streams, architectures and distribution backports.
- Keep existing build requirements as the only input-selection interface.
- Identify resolved providers through portable capabilities for rebuild queries.
- Verify that a rebuild used the required replacement inputs.
- Apply the same rules to local builds, PR builds, merge-queue checks and releases.
- Preserve one shared SRPM per source identity across native architectures.

This proposal does not add a CVE scanner or determine exploitability. It accepts
reviewed rebuild requirements and detects relevant input changes. It does not
require a new general build system or persistent side-tag repositories.

The transaction, acceptance and promotion workflow in
[eternal-os #81](https://github.com/rsturla/eternal-os/pull/81) is related work.
This proposal extends its consumer selection and artifact eligibility rules.
The design PR can land independently; implementation will depend on that work
or an equivalent transaction interface.

## Design from first principles

A build transforms resolved inputs into outputs. Rebuild selection asks whether
an output can still be accepted after an input or repair requirement changes.
This question applies to compilers, libraries, generators, schemas, assets and
other inputs. A language-specific rule in the engine is not required.

The core records these transformations, validates their provenance and evaluates
requirements. It treats capability identities as data. It must support a new
provider and a custom pipeline step without a new language enum, built-in
cataloger or toolchain adapter in rpmx's engine.

The baseline is conservative. Record every input available to a payload-producing
build action as a potential influence on its outputs. This is useful evidence
without claiming that every input was executed or copied. Missing precision can
cause extra rebuilds; it must not omit a required repair.

Shared pipeline steps can refine these relationships. A step can identify its
selected command, incorporated components and affected files through the same
generic reporting interface. Toolchain knowledge and optimizations belong in
these steps. The engine must not interpret Go build information, Cargo graphs,
compiler flags or linker maps to decide rebuild behavior.

Refactor existing modules when needed to establish this model. Do not add a
Go-specific receipt path and later wrap it in a nominally generic interface.
Existing inventories, SBOMs and locks must converge on one model rather than
grow independent provenance systems. This records build actions already run
by rpmx; it does not introduce a replacement action scheduler or cache system.

| Owner | Responsibility |
| --- | --- |
| rpmx core | Existing dependency resolution, immutable input identities, action/output provenance, report validation, receipt serialization, generic requirement evaluation and RPM metadata projection. |
| Shared pipeline steps | Language or tool-specific invocation, evidence collection and conservative relationship refinement. |
| Distribution profiles and policy | Allowed providers, external-package capability annotations, repair requirements and bootstrap choices. |
| Transaction scheduler | Published consumer discovery, source-recipe selection, build ordering, acceptance and promotion. |

## Evidence from toolchains

The following facts inform the proposed policy. The recommended actions are
distribution policy, not claims that upstream mandates a particular RPM design.

| Toolchain or component | Relevant behavior | Recommended rebuild handling |
| --- | --- | --- |
| Go | The toolchain includes its standard library. Binary build information identifies the Go version and modules. | Rebuild consumers of a changed stdlib or runtime in the affected stream. Record the selected compiler, including automatic toolchain selection. |
| Rust | Executables prefer Rust `rlib` dependencies unless dynamic linking is requested. A Rust `staticlib` includes upstream Rust dependencies and stdlib. | Track incorporated stdlib and crates. Handle native dynamic libraries separately. |
| GCC and native C | Outputs can incorporate startup objects and static compiler helpers. Compiler fixes can also change generated code. | Track incorporated runtime inputs and compiler provenance. Rebuild affected compiler outputs when policy requires it. |
| C++ | Template definitions are instantiated into consumers. `libstdc++` also supports shared and static linkage. | Track header-derived code and static libraries even when the executable also uses shared `libstdc++`. |
| glibc | Programs can use shared or static libc. Headers participate in compilation, including source fortification. | A fix confined to the shared runtime normally needs a runtime update. Static libc, startup and header fixes can require consumer rebuilds. |
| Clang and LLVM | Compiler-rt provides runtime support, including sanitizer archives linked into outputs. | Track compiler provenance and incorporated runtime components independently. |
| Python, Perl and Lua | Interpreter code can stay in a separately installed runtime. Native extensions and embedded interpreters have different compatibility requirements. | Ordinary interpreter fixes normally update the runtime. Use ABI rules for extensions and incorporated-component rules for embedded runtimes. |
| Self-contained runtimes | For example, .NET Native AOT applications contain compiled runtime code and can run without an installed .NET runtime. | Track the incorporated runtime rather than assuming a system runtime update repairs the application. |

Sources: [Go toolchains](https://go.dev/doc/toolchain),
[Go binary build information](https://go.dev/ref/mod#go-version-m),
[Rust linkage](https://doc.rust-lang.org/reference/linkage.html),
[GCC link options](https://gcc.gnu.org/onlinedocs/gcc/Link-Options.html),
[C++ template instantiation](https://gcc.gnu.org/onlinedocs/gcc/Template-Instantiation.html),
[glibc fortification](https://sourceware.org/glibc/manual/latest/html_node/Source-Fortification.html),
[Clang toolchain components](https://clang.llvm.org/docs/Toolchain.html),
[Python ABI stability](https://docs.python.org/3/c-api/stable.html),
[Perl maintenance policy](https://perldoc.perl.org/perlpolicy),
[Lua embedding](https://www.lua.org/manual/5.4/manual.html), and
[.NET Native AOT](https://learn.microsoft.com/en-us/dotnet/core/deploying/native-aot/).

## Domain model

| Term | Meaning |
| --- | --- |
| Component | An identifiable body of code or data, such as Go stdlib, a crate, a static runtime or a header implementation. Its logical identity is independent of RPM naming. |
| Provider | The exact RPM or source input that supplied a component or tool. A provider can supply several components. |
| Provider capability | A stable virtual provide through which a provider advertises a logical input identity. It identifies an already resolved input for rebuild queries. |
| Build input | A resolved input available to a build. Availability alone does not prove invocation or incorporation. |
| Build action | A pipeline-step invocation with resolved inputs and an output scope. |
| Relationship | Evidence connecting an output RPM to a component or tool, with a role and confidence. |
| Build receipt | The versioned record of inputs, relationships and evidence for a completed build. |
| Rebuild requirement | A policy rule that identifies affected relationships and the replacement input or repair generation they require. |
| Repair generation | A monotonic revision issued by a policy authority for a component and stream. It advances when consumers must incorporate a repair. |

Record a conservative `build-input` relationship for available inputs. It means
potential influence, not confirmed invocation or incorporation. Steps can also
report more precise roles:

- `runtime`: the output uses a separately installed provider.
- `incorporates`: the output contains provider-derived code or data. Evidence
  can identify static linking, headers, copied sources or an embedded runtime.
- `compiled-by`: a compiler or linker produced the output.
- `generated-by`: a generator produced shipped code or data.

Bootstrap use is a purpose of a build-tool relationship. It is not evidence that
the bootstrap tool's stdlib was incorporated into the final compiler's stdlib.

## Distribution-independent provider contract

Provider RPMs advertise stable virtual capabilities. Toolchains are one use of
this contract. A Go provider could emit:

```text
Provides: rpmx(toolchain:go) = 1.27.4
Provides: rpmx(toolchain:go:1.27) = 1.27.4
```

The standard-library provider advertises its own component capability:

```text
Provides: rpmx(component:go-stdlib) = 1.27.4
Provides: rpmx(component:go-stdlib:1.27) = 1.27.4
```

These names are proposed conventions. They describe upstream toolchain and
component identities; they do not contain distribution RPM names or releases.
Use the same contract for Rust, GCC, Clang and other toolchains. Keep compiler,
runtime, headers and startup components distinct where their rebuild rules differ.
Distinguish implementations when their ABI or command behavior differs. A shared
language name alone does not establish that two compilers are interchangeable.

Existing build requirements remain the only input-selection interface. They
already come from the recipe, profile and shared pipeline steps. A recipe does
not need a second toolchain declaration, a new `build.inputs` block, a special
`rpmx(...)` requirement or a named executable binding.

For example, a recipe can keep its existing form:

```yaml
build:
  packages: [golang-1.27]
  pipeline:
    - runs: go-1.27 build -o "$STAGE/usr/bin/example" ./cmd/example
```

The ordinary resolver installs its dependency closure. rpmx reads the exact
resolved RPMs and records their versioned provides in the build receipt. The
capabilities shown above identify what those packages supply for rebuild
selection. They do not replace `build.packages`, alter command selection or
introduce a new provider-resolution path.

A distribution may name this RPM `golang-1.27`, `go-compiler` or something else.
Its recipes and profiles already express the appropriate build requirements.
Generic rpmx code operates on their resolved package identities and advertised
capabilities. It does not contain a table of compiler package names. Existing
virtual capabilities can still be used in ordinary build requirements when a
consumer prefers them; this feature does not require that migration.

One RPM can advertise several capabilities. Split compiler and stdlib RPMs can
advertise their respective identities. Record the packages actually present in
the resolved closure, including transitive dependencies. Providers omitted by
the resolver cannot be claimed as available inputs.

Executable paths and invocation remain in recipes and shared pipeline steps.
There is no new provider descriptor or command-binding mechanism. A shared step
may observe which executable ran and relate it to an installed provider. Without
that refinement, keep the conservative input relationship. Do not claim that
installing a compiler proves which executable a script invoked.

External or bootstrap RPMs may lack portable identity capabilities. Record their
exact identities anyway. An optional profile annotation can associate additional
capabilities with resolved packages for rebuild queries; it does not select a
package or change its executable. Missing annotations retain conservative
package-level tracking and explicit incomplete coverage, rather than making
otherwise valid build requirements fail.

## One canonical inventory in rpmx

Use a general provenance model for resolved inputs, build actions, output
relationships and components. Reuse rpmx's inventory, lock and bundled-declaration
work where it fits; refactor their interfaces where it does not. Do not force
action provenance into an ecosystem-specific component enum.

Existing Go and Cargo catalogers inspect vendor metadata. That is not proof of
the exact dependency subset incorporated into every binary. Keep their existing
behavior compatible during migration, then move tool-specific collection into
shared pipeline steps. Do not add more language-specific engine catalogers for
this feature.

The common inventory supplies both RPM capability generation and the build
receipt. SBOM output consumes the same records. Recipes must not maintain
independent copies of these facts for each output format.

Each relationship records:

- Output RPM identity, source recipe identity, host and target architectures.
- Logical component or toolchain identity, ecosystem, upstream version and stream.
- Build action, output scope, relationship role, evidence and coverage.
- Provider RPM name, epoch, version, release, architecture and resolved checksum,
  or the corresponding immutable source identity.
- Applicable component content identity or repair generation.

Upstream versions serve component identification. Exact provider revisions
distinguish backports. For example, a fix can change an Eternal RPM release
without changing the version reported by the upstream compiler.

Reuse resolved-lock checksums and existing signing identity receipts. Signing
can change an RPM's envelope checksum; the receipt must connect that envelope
to the tested content. A signing-only change must not trigger consumer rebuilds.
No additional assembled-filesystem or rpmdb hashes are required by this design.

## Queryable RPM metadata

Emit `bundled(...)` provides for incorporated components. Add a separate
namespace for build-tool provenance. These names are illustrative proposals:

```text
Provides: buildinput(toolchain:go:1.27) = <upstream-version>
Provides: bundled(go-stdlib) = <upstream-version>
Provides: builtwith(go) = <upstream-version>
Provides: builtwith(go:1.27) = <upstream-version>
```

Providers advertise their capabilities. Consumers expose conservative
`buildinput(...)` markers and can expose `builtwith(...)` or `bundled(...)` when
evidence supports those stronger claims. The namespaces remain separate so a
consumer RPM cannot satisfy a request to install a compiler. Capability versions
allow portable queries; exact distribution EVRs and checksums remain in receipts.

Normal runtime dependencies remain `Requires`. Neither marker requires users to
install a compiler or treats an embedded library as a shared-library provider.
The scheduler queries matching provides, filters affected revisions and maps
the matching binary outputs back to source recipes.

Preserve version operators, epochs, versions and releases when reading primary
repository metadata. Capability names alone cannot distinguish repaired builds
from affected builds. RPM's ordinary build dependencies do not carry through to
binary packages; see [RPM dependency semantics](https://rpm-software-management.github.io/rpm/manual/dependencies.html).

Use the capability subset for normal repository queries. Publish the full build
receipts with checksum-verified references in repository metadata. Receipts must
be available for as long as their published RPMs remain supported. Temporary
Actions artifacts remain transport and diagnostic storage.

Attach relationships to the outputs they describe. A documentation subpackage
must not claim to contain Go stdlib because another output contains a Go binary.
If evidence only supports a source-package-level association, label that scope
and conservatively rebuild the source recipe without claiming exact inclusion.

## Collection and confidence

The engine creates an action record from the inputs visible to each build step.
It records their immutable provider identities and conservatively associates them
with outputs that the action can affect. Initial scoping can cover every payload
output of the source recipe. It must not create false `bundled(...)` claims for
all those outputs.

Provide one versioned reporting interface for built-in steps, custom steps and
inline scripts. A report references engine-assigned action and input identifiers,
output paths or output selectors, relationship roles, evidence and coverage.
The engine verifies identifiers, path ownership, provider capabilities, conflicts
and deterministic serialization. Exact input identities come from the resolver;
a step cannot replace them with a self-reported RPM name or version.

Reports are claims made by the trusted recipe and its pinned steps. Structural
validation does not prove arbitrary source code behaved honestly. Preserve that
trust scope and the difference between declared, observed and inferred evidence.
Provider metadata is declarative and cannot introduce executable reporters.

A partial report adds facts without removing conservative edges. Narrowing
requires an explicit coverage claim for a defined input and output scope, backed
by the step's contract and evidence. The engine enforces the same refinement
rules for every step. Missing reports, unknown report versions, opaque prebuilt
inputs and unsupported tool modes must retain conservative coverage or fail
strict policy. An empty report must not mean that no inputs were consumed.

Only inputs with no route to shipped outputs can be classified as test-only.
A test step that can modify the staged payload cannot erase its influence by
calling itself a test. Separate output scopes and read-only payload access can
establish that exclusion through the same generic action contract.

For example, a shared Go step could report selected-toolchain and binary build
information. A Rust step could report its relevant build graph. A native link
step could use dependency files and linker maps. A generator could declare
relationships for emitted files. These are optional refinements of the common
mechanism, not prerequisites for a language-specific implementation in the core.

Collect target-specific provider provenance during native binary builds. The
shared SRPM retains portable declarations and source inventories; it must not
gain architecture-specific resolved build inputs or native build receipts.

## Rebuild policy

Keep policy in a versioned repository file, separate from build facts. A
requirement selects a logical component or toolchain capability, stream,
relationship roles and optional architectures. Upstream version ranges support
portable requirements. Distribution policy can further select affected concrete
provider revisions. It also identifies acceptable replacement inputs or a
minimum repair generation.

An upstream capability value is not sufficient evidence of a backported fix.
Bind repair generations and provider approval to a named policy authority. A
generation issued by one distribution must not silently satisfy another's
requirement. Receipts preserve both the logical identity and exact provider
evidence so different naming and patch policies remain distinguishable.

| Relationship or change | Default action |
| --- | --- |
| Incorporated stdlib, static code or implementation headers | Rebuild consumers when the relevant component content changes. |
| Shared runtime implementation with compatible ABI | For verified runtime-only relationships, update the runtime and run relevant acceptance. Unknown build influence still takes the conservative path. |
| Runtime ABI change | Select consumers through compatibility policy and dependency edges. An unchanged SONAME alone does not prove compatibility. |
| Compiler or generator change | Apply an explicit output-affecting rebuild requirement. Mere version inequality does not establish that old outputs are defective. |
| Unknown relevant input coverage | Conservatively select potential consumers or block artifact reuse until coverage is repaired. |

Unrefined build-input relationships conservatively select potentially affected
consumers. Shared steps can identify relevant component content, header scopes
or runtime-only relationships to reduce this set. The engine compares declared
identities and evaluates generic requirements; it does not infer ABI safety
from toolchain names. A mere `compiled-by` or `generated-by` assertion does not
remove potential incorporation edges without coverage evidence.

Component scopes and verified identity equivalence can exclude documentation,
SBOM and signing-only changes. Until that scope is known, rebuild conservatively.

A reviewed requirement is necessary for semantic compiler fixes. Hashes cannot
decide whether a changed optimizer corrects old machine code. A repair generation
can express a backport or hardening requirement without pretending it is an ABI
change. Keep generations separate from RPM publication counters.

Rebuilding a consumer does not repair unchanged vendored source. If an RPM
vendors a vulnerable crate or library, its source inputs must also change.
Publication must reject a rebuild that still incorporates an affected revision.

## Scheduling and artifact eligibility

1. Load a fixed published repository snapshot, its versioned capabilities and
   durable build receipts. Combine these with current recipes and rebuild policy.
2. Select changed recipes and published outputs affected by rebuild requirements.
   Collapse outputs into source recipes, retaining target-specific reasons.
3. Build repaired providers before consumers. Resolve fresh consumer locks
   against the fixed candidate view; an old lock must not bypass a repair.
4. Verify each new receipt satisfies its requirements. A successful compilation
   using the old compiler is not a completed repair.
5. Continue dependency propagation until the required set is complete. Run
   acceptance against the completed candidate repositories, then publish them.

Run the planner and receipt checks through shared local commands. GitHub
workflows dispatch jobs and transfer artifacts; they do not own the policy.

Keep impact selection separate from the worker execution graph. A revision of a
toolchain need not wait for a consumer to appear in the same PR. Query published
relationships so unchanged recipes can enter the rebuild set.

A PR candidate must satisfy the current requirements for its target tree. The
merge queue checks those existing RPMs against latest main and current policy.
It reruns acceptance without recompilation. If a newly published toolchain repair
invalidates a PR artifact, the queue requires a fresh PR build. Passing tests do
not override that requirement. After merge, promotion rechecks eligibility and
can publish the exact queue-accepted bytes.

## Streams, architectures and bootstrap

An update to Go 1.27 normally selects consumers built with the affected Go 1.27
revisions. It does not migrate Go 1.26 consumers to a different stream. Patch
each affected supported stream. Apply architecture filters when a fix is specific
to a target; retain native receipts for both x86_64 and aarch64.

A source recipe rebuild can produce several binary outputs. Initial execution
can rebuild both architectures for simplicity, even when selection identifies
one target. The receipt and policy model must retain that distinction.

Self-hosting compilers need an explicit bootstrap plan. Treat seed-tool use and
the shipped runtime as separate relationships. A repaired bootstrap compiler
does not patch the next compiler's independently built standard-library source.
For code-generation repairs, the plan may require additional self-hosting stages.
Do not use a recursive toolchain version bump as the convergence rule. Require
the final compiler and its consumers to satisfy the declared repair requirement.

## Migration and delivery

1. Refactor the provenance foundation around generic inputs, actions, outputs
   and relationships. Reuse dependency resolution and define capability capture, reporting, coverage, receipts
   and schema compatibility. Prove it with synthetic providers and custom steps.
2. Deliver a complete conservative path through receipt publication, consumer
   discovery, scheduling, queue validation and promotion. It must work without
   any toolchain-specific scanner or adapter.
3. Integrate shared pipeline steps through the reporting contract. Demonstrate
   a compiler, a generator and an incorporated library using the same engine.
4. Add more precise Go, Rust and native-build collection in shared steps. Show
   that refinements reduce rebuilds while preserving required repairs. New
   toolchains must not require changes to the core relationship model.
5. Migrate existing language-specific inventory collection to this interface
   where appropriate. Retire duplicate models instead of maintaining parallel
   metadata-generation paths.

Existing packages have incomplete metadata. Mark coverage explicitly. Rebuild
affected legacy packages conservatively using declared dependencies and build
inputs, or block reuse when a repair cannot be verified. A controlled rebuild
can populate the initial index. Do not infer a clean result from an empty index.

## Validation required before rollout

| Scenario | Required result |
| --- | --- |
| Synthetic providers and arbitrary custom build steps | Complete consumer selection and repaired-input verification without built-in language knowledge. |
| Unreported, partial or unsupported refinement | Keep conservative influence edges; never infer an empty dependency set. |
| New provider namespace and differently named RPMs | Work through capabilities and reports without an engine code change. |
| Test step with payload write access | Preserve potential influence on shipped outputs. |
| Go stdlib fix, unchanged application recipe | Rebuild the application with the repaired stream and verify its receipt. |
| Backport with unchanged upstream version | Select old provider revisions and accept the repaired distribution release. |
| Different distribution RPM names | Use existing build requirements and produce equivalent logical input identities with distinct provider receipts. |
| Split compiler/stdlib packages or several matching providers | Record the provider set selected by existing dependency resolution, without new recipe declarations. |
| External provider without rpmx capabilities | Record the exact RPM identity and incomplete logical coverage; optional profile annotations supply portable identities. |
| Rust stdlib or vendored crate fix | Select incorporated consumers; require a vendored source update where needed. |
| Compatible shared glibc fix | Update the runtime without an unconditional distribution rebuild. |
| glibc startup/header or static-library fix | Select the relevant incorporated-code consumers. |
| GCC/Clang code-generation requirement | Select outputs of affected compiler revisions and verify replacement provenance. |
| Documentation or signing-only change | Do not invalidate consumer code. |
| Multiple streams and target-specific fix | Keep stream and architecture selection correct. |
| Tool installed but unused | Retain potential-input evidence without claiming observed invocation. |
| Missing legacy metadata | Take the conservative path; never report verified safety. |
| Stale PR candidate, passing runtime tests | Block queue reuse until rebuilt with acceptable inputs. |
| Expired Actions artifacts | Discover published consumers from durable repository records. |
| Self-hosting compiler repair | Complete the explicit bootstrap plan without an endless rebuild loop. |

## Alternatives and review questions

A flat reverse-build-dependency graph is a useful conservative baseline. By
itself it cannot distinguish runtime-only use, incorporated code and generated
output. Runtime dependencies alone miss static and generated code. A source
lockfile alone overstates actual incorporation and does not identify all
compiler-provided runtime code. This proposal starts conservatively and refines
those facts through shared-step contracts, without language-specific engine rules.

Before implementation, review these choices:

- Final provider and consumer capability conventions and optional profile annotations.
- Action output scopes and the coverage contract required to refine influence edges.
- The smallest component granularity for glibc and compiler runtime packages.
- How maintainers declare output-affecting fixes and approve repair generations.
- The receipt index format and compatibility rules for older clients.
- Which shared-step contracts can safely narrow conservative component influence.

The initial implementation must work for arbitrary build inputs and custom
steps. Prioritize a clean general model and complete, explainable selection.
Shared-step optimizations can reduce unnecessary rebuilds after that mechanism
works across build, acceptance and promotion.
