# Rebuilds for compiler and embedded-input repairs

Consumers keep their normal build requirements. Provider recipes advertise
portable capabilities such as `rpmx(toolchain:go:1.27)` or
`rpmx(component:glibc-devel:2.44)`. Use `${package.version}` as the value when
that version identifies the input. Package names are not part of the matching
contract. The initial providers cover GCC, Go, glibc build inputs and binutils.
Future Rust or Clang recipes can use the same mechanism.

rpmx embeds exact build-root receipts in binary RPM payloads. Repository
`buildinput(...)` provides connect consumers to providers. Complete component
coverage can remove unused component edges. Missing and partial reports keep
them. No language-specific usage scanner is enabled in this change.

The transaction compares all payload files for portable providers. It excludes
SBOM and receipt files so rebuild counters and input-receipt changes alone do
not propagate. This detects code generation or embedded-code changes even
when ELF interfaces stay the same. Signature-only changes do not propagate.
The existing manual rebuild policy remains a fallback for older providers.

## Require a repaired input

Edit `rebuild-requirements.yaml` with a portable capability and a minimum value:

```yaml
schema: 1
requirements:
  - capability: rpmx(component:go-stdlib:1.27)
    minimum: '1.27.4'
    minimum_evr: '1.27.4-3'
    arches: [x86_64, aarch64]
```

`minimum_evr` and `arches` are optional. The EVR floor distinguishes a repaired
backport from an older package with the same upstream version. Every matching
provider in the receipt must satisfy the floor. Epoch, tilde and caret use RPM
ordering. Keep requirements until no supported publication path can restore
an older affected artifact.

The planner reads checksum-verified published RPM receipts and schedules stale
consumers in addition to changed recipes. A policy-only change reaches the
planner through the normal canary selection; it does not change every recipe
hash. Legacy or incomplete receipts are unknown and require a rebuild while a
requirement applies. Unowned external packages that need repairs block the
transaction and require an upstream repository update.

Before acceptance, the seal gate reads the receipts from the exact candidate
RPMs and unchanged baseline RPMs. Tests cannot override a failed repair check.
A source family replaces all its old outputs. Current build requirements must
resolve repaired provider packages; the scheduler does not alter the solver's
choices or bootstrap a compiler automatically. If a repair needs self-hosting,
prepare the repaired bootstrap generation explicitly before enabling its floor.

The merge queue rejects PR artifacts made under another repair policy or which
omit required repair rebuilds. It then runs the same seal and acceptance gates
against latest main. Promotion checks the current policy and re-reads candidate
and baseline receipts before copying the exact tested bytes. No binary rebuild
is needed when these checks pass.

Receipts remain inside published, signed RPMs in the existing R2 repository.
No extra permanent candidate repository or receipt bucket is required. Candidate
cleanup follows the existing artifact retention policy. An audit can use
`rpmx provenance FILE.rpm` after CI artifacts have expired.

## Rollout

Publish capability-bearing providers before relying on their capability names
in repair policy. A provider that never advertised a capability cannot be
identified as that provider by a distribution-agnostic consumer. Empty policy
keeps legacy repositories usable. Enabling a floor over legacy receipts is
conservative and can select a broad migration rebuild.

A provider can supply finer components later. Shared steps can then emit
complete coverage for specific outputs, without changes to the planner. Keep
the capability spelling stable across package renames and provider replacements.
