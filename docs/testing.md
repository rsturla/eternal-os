# Package testing

Each recipe owns its tests. Tests must exercise useful behavior through the installed package interface.
Upstream suites provide additional source-level coverage. They do not replace installed-package tests.

## Local host setup

Run rpmx as a regular user on Linux. Native bubblewrap builds and tests require:

- Bubblewrap and util-linux `unshare` with `--map-auto` support.
- Linux 5.11 or newer with `close_range(CLOSE_RANGE_CLOEXEC)` permitted by host policy.
- `newuidmap` and `newgidmap`, supplied by `uidmap` or `shadow-utils`.
- At least 65,536 subordinate user IDs allocated to your account in
  `/etc/subuid`, and at least 65,536 subordinate group IDs in `/etc/subgid`.
- A host policy that permits unprivileged user namespaces and namespace-scoped
  `CAP_DAC_OVERRIDE` for private transaction roots.

The shared scripts also use rootless Podman to resolve and assemble roots.
After installing the pinned rpmx revision, check the host with:

```console
rpmx doctor --strict
```

Ubuntu's `bwrap-userns-restrict` AppArmor profile denies capabilities in child
processes, even when user namespace creation is allowed. A host administrator
must adjust that policy for private transactions. The ephemeral CI hosts unload
that specific profile. `rpmx doctor --strict` checks protected-file access as
well as ID mappings.

Ordinary bubblewrap steps run as UID/GID 65534, mapped to your host account,
without capabilities. Transaction tests map your host account to namespace
root and retain only `CAP_DAC_OVERRIDE` for their private writable root.
Both modes use full subordinate ID maps, set no-new-privileges and prevent
nested user namespaces. Missing mapping prerequisites fail setup; rpmx does
not fall back to a single-ID map.

Native commands inherit standard input, output and error, plus explicit runner
handles. Other caller descriptors are closed on exec. This also applies to debug
shells; the parent process keeps its original descriptor flags.

## Run the tests

Install the pinned rpmx revision with `make bootstrap`. Set `RPMX` to use a local build instead.

```console
RPMX=/path/to/rpmx uv run --with pyyaml bash scripts/lint-all.sh --strict
RPMX=/path/to/rpmx ./scripts/build-all.sh --package zlib --output out
rpmx test packages/zlib/package.yaml --install-dir out/zlib/x86_64 \
  --test-profile profiles/eternal.profile.yaml --test zlib-devel/api-behavior
```

The selected test name must match the recipe. Inspect `rpmx plan FILE --json` to list its tests.
`rpmx build` runs the source cases declared in `build.tests`. It produces RPMs without running package acceptance.
The shared build script then runs `rpmx test` against those RPMs. Both phases must pass before it records success.
The bootstrap variants live in `bootstrap/recipes/`. Test those recipes separately from the production recipes.

To test existing production RPMs without rebuilding:

```console
RPMX=/path/to/rpmx ./scripts/test-all.sh --package zlib --rpms out --arch x86_64
RPMX=/path/to/rpmx ./scripts/test-all.sh --rpms out --arch aarch64
make test OUT=out ARCH=x86_64
```

Input directories use `out/<recipe>/<arch>/`. Keep unrelated RPMs outside those directories.
The runner writes `out/tests/results.tsv`, package JSON results, JUnit reports, logs and declared artifacts.
Each package report includes SHA256 manifests for the input RPMs, recipe files
and rpmx binary. It records the repository's rpmx pin.
rpmx reports the exact inputs and resolved environments in `run-report.json`.
Use `scripts/test-all.sh --output DIR` to choose another report directory.
For a direct `rpmx test` invocation, use `--test-output DIR`.
Missing RPMs, invalid recipes, absent runtime tests, skipped tests and failures produce a nonzero exit.

Build and acceptance have separate reports. `rpmx build --output DIR` writes
`DIR/run-report.json` and `DIR/run-report.xml`, with retained case evidence.
The shared build script writes acceptance evidence under
`out/<recipe>/<arch>/acceptance/`, including `results.json`, JUnit, command logs
and declared artifacts. Files survive temporary workspace cleanup and CI uploads
the output tree after failures.

A report has document `rpmx-run-report`, version 1. Check `outcome`, not just the
process exit status. Complete acceptance requires `acceptance: completed` and
all planned cases with status `passed`. `skipped`, `not-run`, and an incomplete
run do not establish coverage. Skipped or not-run cases make the run incomplete.
A build report records `build_tests_requested`
and its source cases separately from acceptance.

The shared scripts gate both phases before stamps, private dependency promotion
or publication. `--no-tests` skips both phases in these scripts; the direct
`rpmx build --no-tests` flag skips only `build.tests`. With `--arch all`, the shared
build script invokes each declared architecture separately and retains their
reports. Private toolchain and Python bootstrap dependency evidence is copied
under `out/test-reports/`; private dependency RPMs stay out of that report tree.
The Python helper accepts one concrete architecture per invocation.

The lint and Python bootstrap helpers require Python and PyYAML. Use a virtual
environment, or run them through `uv run --with pyyaml` as above.

Run the repository helper regressions without compiling package sources:

```console
uv run --with pyyaml make test-tools
```

`make check` and CI run the same `scripts/test-tools.sh` entry point. These tests
check dependency ordering, cache invalidation, report retention and failure
handling. They complement the package tests below.
Candidate-profile checks emit small fixture RPMs and require host `rpm` and rpmx.

To reproduce a CI runtime failure on the same Ubuntu runner architecture,
dispatch the existing `CI` workflow against an uploaded RPM artifact:

```console
gh workflow run CI --ref "$(git branch --show-current)" \
  -f artifact_run=42983578558 -f package=glibc-2.44 -f arch=x86_64
```

This mode downloads `rpm-foundations-ARCH` from the specified run and calls
`scripts/test-all.sh` without rebuilding package sources. Set
`-f artifact_name=rpm-NAME-ARCH` to use a normal package artifact instead.
The selected branch supplies the recipes and pinned rpmx revision. Tests use
the current production test profile; this is not a replay of the original
dependency lock. Reports include the source run URL and head SHA, GitHub's
artifact ID and digest, and the usual RPM and resolved-root manifests.
Replay reports upload even after a test fails. Separate architectures and
normal builds have independent concurrency groups.

The shared build and test scripts use `profiles/eternal.profile.yaml` for runtime
test repositories. Bootstrap build exclusions therefore do not restrict production
test dependencies. Override this with `--test-profile FILE` when necessary.
Each test still installs only its selected outputs, baseline tools and explicit
test dependencies. The profile's seed package list does not populate test roots.
Standalone runtime testing reads target metadata without preparing a build root.

To test consumers against unpublished dependency fixes, first build the selected
foundation packages. Choose a candidate destination that does not already exist:

```console
uv run --with pyyaml bash scripts/build-test-dependencies.sh \
  --package kernel-headers --package glibc-2.44 --package rpm --package openssl3 \
  --arch x86_64 --output out --rpms .work/new-test-dependencies
uv run --with pyyaml bash scripts/build-all.sh --package python-3.14 \
  --arch x86_64 --output out --test-rpms .work/new-test-dependencies
```

The first script builds only the requested foundation names, in the order
`kernel-headers`, `glibc-2.44`, `rpm`, `openssl3`. Each build runs its full tests.
Later builds can use earlier successful candidates in their test roots. A failure stops the
chain and retains its normal output evidence.

When selecting compiler streams, add their names with `--package gcc-13` through
`--package gcc-16`. The script first builds a private OpenSSF policy seed, then
only the selected compilers. These raw builds run their source tests but remain
quarantined. Once every producer succeeds, the complete candidate cohort passes
standalone acceptance against the Eternal production profile, including all
OpenSSF wrapper tests. Only then do selected package outputs become consumer
dependencies. The seed is exported only when explicitly selected. Source identity,
rpmx identity, complete planned outputs and source-test reports are checked again
before acceptance; a changed or incomplete producer cannot enter the pool.

CI runs the selected compiler producers in parallel and uses the same entry points
locally available for separate producer workspaces:

```console
uv run --with pyyaml python scripts/compiler-cohort.py produce-seed \
  --arch x86_64 --output quarantine/openssf-compiler-options
uv run --with pyyaml python scripts/compiler-cohort.py produce \
  --package gcc-13 --arch x86_64 --seed quarantine/openssf-compiler-options \
  --output quarantine/gcc-13
uv run --with pyyaml bash scripts/build-test-dependencies.sh \
  --package gcc-13 --arch x86_64 --compiler-inputs quarantine \
  --output out --rpms .work/new-compiler-candidates
```

Use the same `--build-release` value for all commands when supplied. Keep producer
artifacts under their quarantine names; they are not release artifacts. Build logs
and source-test evidence remain in each producer directory on failure. Acceptance
evidence is under `out/test-reports/compiler-cohort/ARCH/`. A compiler-free selection
keeps the ordinary foundation path and does not build any compiler streams.

`--test-rpms DIR` accepts a directory of binary RPMs for one target architecture,
including noarch outputs. It requires host `rpm`, rpmx, Python and PyYAML.
The helper validates RPM headers, copies an immutable repository snapshot, and
excludes those exact output names from the other test repositories. It preserves
the rest of the selected test profile. Source build repositories stay unchanged.
Candidate payload changes invalidate cached test outcomes. Source RPMs, foreign
architectures and conflicting versions of one output are rejected.

CI uses the same scripts. Only foundation packages present in the selected build
plan run before consumers. Their successful binary outputs become consumer test
dependencies; failed foundation evidence is still uploaded. An unrelated package
selection does not rebuild or publish these foundations. Without `--test-rpms`,
foundation dependencies resolve from the selected test profile's repositories.
A source recipe fix does not repair dependency metadata that is already published.

Normal Python matrix builds use published interpreter-qualified dependencies
from the Eternal repository. For an unpublished interpreter stream, invoke
`scripts/build-python.py` explicitly. Its dependency ordering includes test tools;
both build and test profiles see its private dependency repository.
[Issue 41](https://github.com/rsturla/eternal-os/issues/41) tracks a replacement
for this explicit bootstrap path.
An existing-RPM run never executes source suites.

Use a native machine for each supported architecture. A cross compile does not
prove target runtime behavior. Use `--runner qemu` when the execution environment
supports that runner.

To save the resolved acceptance environments for an exact replay:

```console
rpmx test packages/zlib/package.yaml --install-dir out/zlib/x86_64 \
  --test-profile profiles/eternal.profile.yaml --save-environment out/zlib-environments
rpmx test packages/zlib/package.yaml --install-dir out/zlib/x86_64 \
  --replay out/zlib-environments --offline
```

A saved environment contains the prepared roots and private bindings. An arbitrary
root directory or bare dependency lock is not a replay input. Replay validates
its binding to the recipe, selected RPMs and execution policy. Do not combine
`--replay` with `--test-profile`. Fresh roots require online resolution and
assembly. `scripts/test-all.sh` prepares fresh roots and does not offer offline
runs. Commands have no external network by default; requesting network access
makes the case unavailable in an offline run.

## Define tests

Choose exactly one execution form:

| Form | Use |
| --- | --- |
| `script` | Strict Bash with error, unset-variable and pipeline checks |
| `argv` and optional `expect` | A direct command with exact status and output assertions |
| `pipeline` | Reusable rpmx steps, including upstream suite runners |

```yaml
tests:
  - name: reject-missing-match
    packages: [grep]
    argv: [grep, missing, /dev/null]
    expect:
      exit-code: 1
      stdout: ''
      stderr: ''
```

Shell `-c` commands in `argv` are errors. Move their text to `script`.

Set `timeout` on a test to bound the whole case, including all its pipeline steps.
A step's own deadline can shorten its remaining allowance. Use a positive whole
number followed by `s`, `m`, or `h`. Zero, fractions, missing units and overflow
fail recipe validation. GCC and glibc source suites allow four hours per case;
production binutils allows two hours.

```yaml
build:
  tests:
    - name: upstream
      packages: [dejagnu]
      timeout: 4h
      files: tests
      script: bash "$TEST_FILES/upstream.sh"
```

An unchecked command failure fails a strict script. Bash has exceptions for conditions and `&&` or `||` lists.
Check expected failures explicitly. Do not hide a failed assertion behind a successful final command.
Avoid `producer | grep -q pattern` under `pipefail` when an early reader exit can give the producer SIGPIPE.
Write output to a file, then check the file when that behavior matters.

## Test environments

| Declaration | Available input | Purpose |
| --- | --- | --- |
| `build.tests` | Independent source-workspace copy and pinned build closure plus case tools | Upstream source suites |
| Output or recipe `tests` | Selected RPM closure and explicit case tools | Runtime behavior and installed consumer interfaces |
| `tests` with `mode: transaction` | Private writable RPM root and supplied binary RPMs | Installation, upgrade, scriptlets, configuration and erase |

`build.tests` and acceptance cases use the same command, fixture and report syntax.
Source cases reject transaction mode and network access. Each source case extends
the pinned build closure with its own tools; those tools do not enter the build
root or another case. Tools needed during configure or compilation remain real
`build.packages` dependencies.

Output-level acceptance selects the named output and its declared runtime siblings.
Recipe-level acceptance installs all outputs. Use these for integration, not for
minimal dependency checks. Every case has a private writable workspace. The
candidate RPM payload is exposed read-only as `TEST_PACKAGE_ROOT` for layout and
ELF checks; dependency payloads are excluded from that view. Do not use `$STAGE`
to check acceptance. Prepared roots can be shared, but case writes cannot leak.

Declare case-only tools in that case's `packages` list.

Reusable steps add their declared tools. Strict scripts infer Bash and coreutils.
Add other commands only when the test uses them.
Tests that look up their user or group need real account data in the root.
For example, glibc's upstream suite declares `setup` as a test dependency.
Keep runtime tests separate from compiler tests, since a compiler can pull extra runtime libraries into the test root.

Compiler-policy tests check branch protection on code produced by the wrapper,
without dependency startup objects. GCC and glibc tests check their own installed
startup objects separately. GCC tests also link and run consumers through the
real startup closure. Keep both checks: a wrapper's flags do not protect runtime
objects that GCC builds with its in-tree compiler.

## External files

Use one package-local directory for small test inputs:

```text
packages/example/
  package.yaml
  tests/
    consumer.c
    include/check.h
    input.txt
    expected.txt
```

Declare `files: tests`. rpmx copies regular files recursively and exposes a private read-only copy through `TEST_FILES`.
The recipe digest and SRPM include fixture contents. Internal execution snapshots
preserve file contents and permission modes, so checkout edits cannot change a running case.
Fixture changes invalidate build-cache inputs. Copy an input into the case workspace before modifying it.
Symlinks, parent traversal, missing directories and empty fixture directories are errors.
RPM fixtures under a recipe's `tests/` directory are trackable in Git.
Keep their source, checksums and signing-key provenance beside them.
Use `bash -euo pipefail "$TEST_FILES/check.sh"` when a fixture is a shell script.
Executable fixture modes are preserved in the internal snapshot.
Keep a shebang executable in Git to satisfy the repository's file checks.

Use pinned, checksummed source archives for large upstream test collections.
Do not fetch test data or dependencies during test execution.

## Debug a source-suite failure

Use `rpmx build packages/NAME/package.yaml --keep-workdir` to retain the source
workspace and stage. rpmx prints their paths. Open the recipe's build root with:

```console
rpmx shell packages/NAME/package.yaml --workspace /saved/build --stage /saved/stage
```

The shell uses the build sandbox's identity, ID mappings, environment policy and
mounts. Its root and any target sysroot stay read-only. Workspace and stage
writes remain owned by your host account. Terminal streams stay attached;
debug sessions have no build-step deadline or captured test logs. The shell
opens a build environment; installed and transaction tests have separate roots.

## Coverage expectations

Review every functional output. Documentation-only outputs need no artificial test.
Data outputs need checks through their consumer when the data changes runtime behavior.
Metapackages need useful installed-closure checks.

| Package interface | Required checks where applicable |
| --- | --- |
| Command | Real input and exact results, exit status, rejected input, relevant options |
| Compression or archive | Round trip, independent content check, corrupt or truncated input, nontrivial files |
| Shared library | Real API calls, error paths, data ownership and cleanup |
| Development output | Compile and run an installed consumer using its headers and metadata |
| Static output | Link the intended archive explicitly and verify the result uses it |
| Compiler or linker | Multiple translation units, C and C++, optimization, shared and static links, diagnostics |
| Interpreter | Standard-library behavior, optional extension modules, child processes and invalid input |
| Security or packaging tool | Local policy or database operations and real package lifecycle checks |
| Locale or time data | Fixed historical or future instants with explicit locale and timezone |

Version output and file existence are diagnostics. They are not sufficient behavioral coverage.
Preserve hardening checks, but do not count them as application functionality tests.

## Review reliability

Use deterministic inputs and fixed expected output. Set locale or timezone when output depends on them.
Avoid wall-clock dates, sleeps and assumptions about host users, devices, privileges or network services.
For local services, bind an ephemeral loopback port, wait for readiness and clean up children on every exit.
Do not enable the external network to make a test pass.

Use independent checks for round trips. Two operations can share the same defect.
For static-link tests, check the resulting executable rather than only the archive's presence.
For a consumer installation check, let the tested output pull in its own required
headers, libraries and interpreters. Declare independent test tools in `packages`.
Installing a missing runtime requirement explicitly can make a broken output pass.
For representative tests, deliberately break an expectation or fixture and confirm a failure.
Run tests twice when a previous failure suggests shared state or ordering dependence.

## Readable tests

Name each test after the behavior it checks. Keep setup, the operation, and its
expected result easy to identify. Use named cases or functions when one fixture
checks several independent behaviors.

Put each assertion on a separate line. Failure messages should identify the
case and show the expected and actual results when useful. Shell fixtures should
report the failing command and line. Explain unusual inputs and linking checks
with short comments. Avoid comments that only repeat the next command.

Review the assertion itself. A successful subprocess, an existing output file,
or a round trip alone can miss incorrect behavior. Check the relevant contents,
error, linkage, or side effect through the interface that users consume.

## Reports and production decisions

Use `artifacts` to preserve literal workspace paths such as `build/meson-logs` or an upstream JUnit file.
Missing artifact paths are ignored. Artifact paths cannot escape the workspace.
Generated relative symlinks are preserved without following them, including contained dangling links.
Absolute links, targets outside the workspace and special files are errors.
Full stdout and stderr remain in separate test log files. JUnit records failures
and evidence paths.

JSON case results distinguish `passed`, `failed`, `skipped` and `not-run`.
Skipped and not-run cases make the run `incomplete`.
Environment errors and missing input RPMs are not passes. A declared test that has not run is not a pass.
Record the RPM identity, architecture, rpmx revision and dependency-root evidence with the report.

Before release, run the full build and runtime tests on both supported architectures.
Check package combinations and upgrades in addition to isolated output tests.
Review every skip and failure. Passing tests establish the tested behavior in the recorded environment.
They do not prove that the package has no defects or security vulnerabilities.
