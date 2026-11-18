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
- A host policy that permits unprivileged user namespaces and the namespace-scoped
  capabilities needed for private RPM transactions.

The shared scripts require Bash, Python 3.11 or later, and `jq`. They use
rootless Podman to resolve and assemble roots.
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
root with a restricted capability set for file ownership, permissions, identity
changes and chroot in their private writable root.
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
`rpmx build` runs the source cases declared in `build.tests`. It produces RPMs without running installed-package tests.
The shared build script then runs `rpmx test` against those RPMs. Both phases must pass before it records success.
The bootstrap variants live in `bootstrap/recipes/`. Test those recipes separately from the production recipes.

To test existing production RPMs without rebuilding:

```console
RPMX=/path/to/rpmx ./scripts/test-all.sh --package zlib --rpms out --arch x86_64
RPMX=/path/to/rpmx ./scripts/test-all.sh --rpms out --arch aarch64
make test OUT=out ARCH=x86_64
```

Input directories use `out/<recipe>/<arch>/`. Keep unrelated RPMs outside those directories.
Use `--include-optional-tests` to select optional installed-package cases as well.
A recipe with no selected installed-package cases cannot report a passing test run.
The runner writes `out/tests/results.tsv`, package JSON results, JUnit reports, logs and declared artifacts.
Each package report includes SHA256 manifests for the input RPMs, recipe files
and rpmx binary. It records the repository's rpmx pin.
rpmx reports the exact inputs and resolved environments in `run-report.json`.
Use `scripts/test-all.sh --output DIR` to choose another report directory.
For a direct `rpmx test` invocation, use `--test-output DIR`.
Missing RPMs, invalid recipes, absent package tests, skipped tests and failures produce a nonzero exit.

Source suites and installed-package tests have separate reports. `rpmx build --output DIR` writes
`DIR/run-report.json` and `DIR/run-report.xml`, with retained case evidence.
The shared build script writes installed-package test evidence under
`out/<recipe>/acceptance/<arch>/`, including `results.json`, JUnit, command logs
and declared artifacts. Test progress and diagnostics stream to the terminal
as they run and are also retained in `run.log`. Files survive temporary workspace
cleanup and CI uploads the output tree after failures.

A report has document `rpmx-run-report`, version 1. Check `outcome`, not just the
process exit status. A complete installed-package run requires `acceptance: completed` and
all planned cases with status `passed`. `skipped`, `not-run`, and an incomplete
run do not establish coverage. Skipped or not-run cases make the run incomplete.
A build report records `build_tests_requested`
and its source cases separately from installed-package results.

By default the shared scripts gate both phases before successful build stamps
or private dependency promotion. CI defers installed-package tests to its parallel test matrix
and gates publication on both phases. `--no-tests` skips both phases in these scripts; the direct
`rpmx build --no-tests` flag skips only `build.tests`. Private OpenSSF seed build
output stays under `.work/toolchain-out/`.
The explicit Python bootstrap helper keeps dependency evidence under
`.work/python-deps/ARCH/NAME/` and accepts one concrete architecture per invocation.

The lint and Python bootstrap helpers require Python and PyYAML. Use a virtual
environment, or run them through `uv run --with pyyaml` as above.

Run the repository helper regressions without compiling package sources:

```console
uv run --with pyyaml make test-tools
```

`make check` and CI run the same `scripts/test-tools.sh` entry point. These tests
check dependency ordering, cache invalidation, report retention and failure
handling. They complement the package tests below.

The shared build and test scripts use `profiles/eternal.profile.yaml` for runtime
test repositories. Bootstrap build exclusions therefore do not restrict installed-package
test dependencies. `scripts/test-all.sh` accepts `--test-profile FILE` to override
that policy.
Each test still installs only its selected outputs, baseline tools and explicit
test dependencies. The profile's seed package list does not populate test roots.
Standalone installed-package testing reads target metadata without preparing a build root.

All selected packages build concurrently in CI, including compilers and core
libraries. There are no package categories or ordered foundation stages.
Each build runs its source suites. After the candidate artifacts are available,
installed-package test jobs run concurrently against those artifacts. Publication
requires both matrices to pass. Cross-package tests use candidate dependencies
without making unrelated builds wait for them.

The same separation is available locally:

```console
uv run --with pyyaml bash scripts/build-all.sh --package gcc-16 \
  --arch x86_64 --output out --defer-acceptance
uv run --with pyyaml bash scripts/test-all.sh --package gcc-16 \
  --arch x86_64 --rpms out --candidate-rpms out --output out/tests
```

`--defer-acceptance` runs source suites but leaves installed-package and transaction tests
for the standalone command. Its build stamp differs from a fully accepted build.
Private policy seeds are built without installed-package tests, so building
another package does not start hidden package tests. The selected compiler-policy
package has its own test job. Without this option, local builds run both
phases as before.

`--candidate-rpms DIR` takes binary outputs from `DIR/NAME/ARCH/`, including
noarch outputs stored in that architecture's directory. Source RPMs and nested
test fixture RPMs are excluded. The shared helper checks the artifact layout and
duplicate filenames before pooling these bytes. rpmx reads the RPM headers and imports candidates into its
content-addressed store. Candidate providers take precedence over published
providers while the production repository policy remains in effect.
A package absent from the candidate set resolves from published repositories.
The build records its release policy beside the RPMs. Standalone tests read it,
so cached rolling RPMs keep their original release suffix. `--build-release`
can override that recorded value for explicit local inputs.

Use `--candidate-rpms` on the standalone test command when dependencies have
unpublished binary outputs. It does not change source build roots. A source
recipe fix does not repair dependency metadata that is already published.

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

To save the resolved installed-package test environments for an exact replay:

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
runs. Cases default to `network: false`. An installed-package case that declares
`network: true` is unavailable in an offline run, making that run incomplete.

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
fail recipe validation. The glibc source suites allow four hours per case;
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

`build.tests` and installed-package cases use the same command, fixture and report syntax.
Source cases reject transaction mode and `network: true`. Both source and
installed-package cases default to `network: false`. Each source case extends
the pinned build closure with its own tools; those tools do not enter the build
root or another case. Tools needed during configure or compilation remain real
`build.packages` dependencies.

An installed-package case can request external access explicitly when it tests
an external integration. For example, a case against a controlled test service
can check the exact response:

```yaml
outputs:
  - name: example-client
    tests:
      - name: external-health
        network: true
        packages: [curl]
        argv: [curl, --fail, --silent, --show-error, https://service.example/health]
        expect:
          exit-code: 0
          stdout: "healthy\n"
          stderr: ''
```

Replace the example endpoint with the controlled service. Prefer bundled inputs
or a loopback service when they can exercise the same behavior. `network: true`
is supported for installed-package cases, not for `build.tests`.

Output-level tests select the named output and its declared runtime siblings.
Recipe-level tests install all outputs. Use these for integration, not for
minimal dependency checks. Every case has a private writable workspace. The
candidate RPM payload is exposed read-only as `TEST_PACKAGE_ROOT` for layout and
ELF checks; dependency payloads are excluded from that view. Do not use `$STAGE`
to check installed-package behavior. Prepared roots can be shared, but case writes cannot leak.

Declare case-only tools in that case's `packages` list.

Reusable steps add their declared tools. Strict scripts infer Bash and coreutils.
Add other commands only when the test uses them.
Tests that look up their user or group need real account data in the root.
For example, glibc's upstream suite declares `setup` as a test dependency.
Keep installed-package runtime checks separate from compiler checks, since a
compiler can pull extra runtime libraries into the test root.

Compiler-policy tests check branch protection on code produced by the wrapper,
without dependency startup objects. Compiler and C library packages must test
their own installed startup objects and linked programs separately.

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
opens a build environment; installed-package and transaction tests have separate roots.

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
Declare `network: true` only when external access is part of the behavior under test.
Do not use it to fetch undeclared fixtures or dependencies.

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

Before release, run source suites and installed-package tests on both supported architectures.
Check package combinations and upgrades in addition to isolated output tests.
Review every skip and failure. Passing tests establish the tested behavior in the recorded environment.
They do not prove that the package has no defects or security vulnerabilities.
