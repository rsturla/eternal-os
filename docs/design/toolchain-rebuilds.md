# Toolchain and bundled-component rebuilds

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

- Record incorporated components and build tools separately from runtime dependencies.
- Select consumer rebuilds across language toolchains and native libraries.
- Distinguish toolchain streams, architectures and distribution backports.
- Resolve toolchains through stable capabilities rather than distribution RPM names.
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
| Toolchain capability | A stable virtual provide through which a provider advertises a logical toolchain or component. |
| Build input | A resolved input available to a build. Availability alone does not prove invocation or incorporation. |
| Relationship | Evidence connecting an output RPM to a component or tool, with a role and confidence. |
| Build receipt | The versioned record of inputs, relationships and evidence for a completed build. |
| Rebuild requirement | A policy rule that identifies affected relationships and the replacement input or repair generation they require. |
| Repair generation | A monotonic revision issued by a policy authority for a component and stream. It advances when consumers must incorporate a repair. |

Record four relationship roles:

- `runtime`: the output uses a separately installed provider.
- `incorporates`: the output contains provider-derived code or data. Evidence
  can identify static linking, headers, copied sources or an embedded runtime.
- `compiled-by`: a compiler or linker produced the output.
- `generated-by`: a generator produced shipped code or data.

Bootstrap use is a purpose of a build-tool relationship. It is not evidence that
the bootstrap tool's stdlib was incorporated into the final compiler's stdlib.

## Distribution-independent provider contract

Toolchain RPMs advertise stable virtual capabilities. A Go provider could emit:

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

A recipe requests a capability such as `rpmx(toolchain:go:1.27)`. The distribution
profile controls allowed streams, repositories and provider policy. The resolver
selects concrete packages, verifies their capabilities and records the exact
provider revisions. RPMs named `golang-1.27`, `go-compiler` or another name can
satisfy the same recipe contract if they supply the required toolchain.

Providers also ship a versioned toolchain descriptor. It connects the capability
to executable paths, host and target support, component capabilities and evidence
adapters. RPM capabilities identify providers; they cannot by themselves describe
which command to execute or how split compiler and stdlib packages relate.

Resolve descriptor component dependencies against the same locked package set.
Require compatible streams and revisions across split compiler and runtime providers.
Validate executable ownership and component evidence against the selected
providers. Bind build steps to the selected executable, rather than whichever
`go`, `gcc` or `rustc` happens to appear first in `PATH`. Do not run arbitrary
probe scripts supplied through untrusted metadata.

This contract supports both split and combined packaging. One RPM can provide
several components; several RPMs can supply one toolchain. If several providers
match, use normal repository resolution and profile constraints. Record the
selected provider set. Fail if the descriptor and the actual tool selection
disagree; do not silently guess from RPM names.

External and bootstrap RPMs may lack this contract. A distribution profile can
declare an equivalent compatibility binding for a concrete package or existing
virtual capability. That binding supplies the descriptor and verifies the
resolved provider version and files. Package-name mapping belongs only in this
distribution integration layer. Generic rpmx adapters and rebuild rules use
logical identities and capability values.

## One canonical inventory in rpmx

Extend rpmx's existing component inventory and bundled declarations. It already
supports output associations, evidence, confidence and source declarations.
Its Go and Cargo catalogers inspect vendor metadata; that is not proof of the
exact dependency subset incorporated into every binary.

The extended inventory supplies both RPM capability generation and the build
receipt. SBOM output consumes the same records. Recipes must not maintain
independent copies of these facts for each output format.

Each relationship records:

- Output RPM identity, source recipe identity, host and target architectures.
- Logical component or toolchain identity, ecosystem, upstream version and stream.
- Relationship role, incorporation mechanism, evidence and confidence.
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
Provides: bundled(go-stdlib) = <upstream-version>
Provides: builtwith(go) = <upstream-version>
Provides: builtwith(go:1.27) = <upstream-version>
```

Toolchain providers advertise `rpmx(toolchain:...)`. Consumers advertise
`builtwith(...)`. Keeping those namespaces separate prevents a consumer RPM
from satisfying a request to install a compiler. Capability versions allow
portable queries; exact distribution EVRs and checksums remain in receipts.

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

Start with explicit declarations and toolchain adapters. Build-step declarations
identify intended tools; resolved locks identify their available provider RPMs.
Adapters verify selection where the toolchain exposes reliable evidence.

- Go: inspect binary build information and bind the selected toolchain capability
  to its resolved provider set. Reject unexplained toolchain switching or downloads.
- Rust: capture the selected compiler, stdlib and relevant Cargo build graph.
  A lockfile can include build, test, optional and unused dependencies. Do not
  advertise every lockfile entry as confirmed embedded code.
- C/C++: support explicit component and tool declarations first. Later adapters
  can use linker maps, dependency files and compiler invocation records.
- Generators: support explicit output relationships for generated code. This
  covers cases that cannot be discovered through ELF dependencies.

Keep declared, observed and conservatively inferred relationships distinct.
An input installed in a build root is not automatically `compiled-by` evidence.
Missing evidence must not be interpreted as proof that an output is unaffected.
Unexplained prebuilt objects require a declared origin or fail strict policy.

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
| Shared runtime implementation with compatible ABI | Update the runtime and run relevant acceptance. No blanket consumer rebuild is required. |
| Runtime ABI change | Select consumers through compatibility policy and dependency edges. An unchanged SONAME alone does not prove compatibility. |
| Compiler or generator change | Apply an explicit output-affecting rebuild requirement. Mere version inequality does not establish that old outputs are defective. |
| Unknown relevant input coverage | Conservatively select potential consumers or block artifact reuse until coverage is repaired. |

Content comparison should cover the relevant provider component, not all files
from its source package. Documentation, SBOM and signing-only changes must not
invalidate consumers. Initial adapters can over-select within a declared role
when finer evidence is unavailable.

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

1. Add the capability contract, descriptor schema, common inventory relationships
   and explicit declarations in rpmx. Define ordering and schema compatibility.
2. Add versioned capability ingestion and durable receipt publication. Validate
   receipt references and retain them with supported package history.
3. Implement Go end to end, including stdlib tracking and selected-toolchain
   verification. Exercise consumer selection with an unchanged application recipe.
4. Connect requirements to transaction scheduling, queue validation and promotion.
5. Add Rust and C/C++ adapters. Improve incorporation precision without changing
   the scheduler's relationship model.

Existing packages have incomplete metadata. Mark coverage explicitly. Rebuild
affected legacy packages conservatively using declared dependencies and build
inputs, or block reuse when a repair cannot be verified. A controlled rebuild
can populate the initial index. Do not infer a clean result from an empty index.

## Validation required before rollout

| Scenario | Required result |
| --- | --- |
| Go stdlib fix, unchanged application recipe | Rebuild the application with the repaired stream and verify its receipt. |
| Backport with unchanged upstream version | Select old provider revisions and accept the repaired distribution release. |
| Different distribution RPM names | Resolve the same recipe capability and produce equivalent logical relationships with distinct provider receipts. |
| Split compiler/stdlib packages or several matching providers | Lock the selected provider set and bind the descriptor to those packages. |
| External provider without rpmx capabilities | Use an explicit profile binding, or fail with a missing-provider error. |
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

Rebuilding every build-time reverse dependency is simple but treats documentation
tools, test tools and compilers alike. Runtime dependencies alone miss static
and generated code. A source lockfile alone overstates actual incorporation and
does not identify all compiler-provided runtime code. This proposal keeps those
facts distinct and lets conservative policy use all available evidence.

Before implementation, review these choices:

- Final capability names, toolchain descriptor schema and public recipe syntax.
- The smallest component granularity for glibc and compiler runtime packages.
- How maintainers declare output-affecting fixes and approve repair generations.
- The receipt index format and compatibility rules for older clients.
- Whether initial Go/Rust toolchain updates conservatively invalidate all
  consumers in the stream, or only changed component and tool roles.

The initial implementation should prioritize complete, explainable selection.
More precise tracing can reduce unnecessary rebuilds after the repair mechanism
works across build, acceptance and promotion.
