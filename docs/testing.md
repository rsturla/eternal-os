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
rpmx test packages/zlib/package.yaml --test zlib-devel/api-behavior
```

The selected test name must match the recipe. Inspect `rpmx plan FILE --json` to list its tests.
`rpmx build` and `rpmx test` without `--install-dir` run build-stage and runtime tests.
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
and rpmx binary. It records the repository's rpmx pin and the supplied root lock's hash.
rpmx preserves the resolved test dependency locks under each report's `artifacts/environments/` directory.
Use `--output DIR` to choose another report directory.
Missing RPMs, invalid recipes, absent runtime tests, skipped tests and failures produce a nonzero exit.

Normal builds also retain evidence. The shared build script keeps test stdout,
stderr and declared artifacts in `out/<recipe>/<arch>/test-results/`, including
source-suite failures. Direct `rpmx build --output DIR` invocations use
`DIR/<arch>/test-results/`. These files survive build-workspace cleanup.
`scripts/build-all.sh` writes the package's JUnit report at
`out/<recipe>/<arch>/junit.xml` and prints its evidence directory. With
`--arch all`, the shared build script runs each architecture declared in the
bootstrap profile separately. It preserves each report and attempts the other
architectures if one fails. It collects reports
from private builds under `out/test-reports/`:

- `toolchain/<seed-identity>/` contains the compiler-policy seed's reports.
- `python/<consumer>/<arch>/<dependency>/<input-identity>/` contains reports for
  each private Python dependency, with copied test results. The consumer's
  evidence stays beside its RPM outputs.

Collection runs after successful and failed builds. Cached Python dependencies
also contribute their previous reports. The identities include the relevant
recipe inputs and test policy. Reports contain no private dependency RPMs.
Each rpmx invocation has its own JUnit path; one matrix build aggregates its
cells into that report. CI uploads the output tree after failures too.
With `--no-tests`, the scripts do not request or collect test reports.
For direct `scripts/build-python.py` calls, reports default to
`OUTPUT/test-reports/`; use `--test-reports DIR` to choose another destination.
The Python bootstrap helper requires one concrete `--arch` value per invocation.

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

Python matrix builds prepare unpublished interpreter and module dependencies
through `scripts/build-python.py`. Its ordering includes test tools. Both build
and test profiles see the private dependency repository. This bootstrap helper
remains subject to the removal gates in [issue 41](https://github.com/rsturla/eternal-os/issues/41).
An existing-RPM run does not execute build-stage suites.

Use a native machine for each supported architecture. A cross compile does not prove target runtime behavior.
Use `--runner qemu` when the prepared execution environment supports that runner.
Use `--root-lock FILE` to provide build and target metadata instead of automatic build-root preparation.
The shared scripts still use `--test-profile` for runtime repositories.
For a pinned runtime policy, call `rpmx test` directly with `--test-root-lock FILE` and omit `--test-profile`.
Fresh runtime roots require online resolution and assembly, including with a pinned lock.
For an offline run, pass `--test-root ROOT_DIR --install-dir RPM_DIR --offline`
to `rpmx test FILE`, using an assembled test root and its saved lock.
`scripts/test-all.sh` prepares fresh roots and does not support offline runs.
Test commands themselves run without the external network.

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
    stage: installed
    packages: [grep]
    argv: [grep, missing, /dev/null]
    expect:
      exit-code: 1
      stdout: ''
      stderr: ''
```

Shell `-c` commands in `argv` are errors. Move their text to `script`.

Set a custom deadline on the pipeline step with a duration string, such as `timeout: 4h`.
Use a positive whole number followed by `s`, `m`, or `h` for seconds, minutes, or hours.
Zero, fractions, missing units, and overflowing durations fail recipe validation.
A step value overrides `--step-timeout`; other steps inherit that command default.
Use a `pipeline` containing a `runs` step when a test script needs a custom deadline.
GCC and glibc source suites allow four hours per step; production binutils allows two hours.
Other test steps retain the one-hour default unless their measured run time requires a change.

```yaml
tests:
  - name: upstream
    stage: build
    pipeline:
      - runs: |
          make -C build check
        timeout: 4h
```

An unchecked command failure fails a strict script. Bash has exceptions for conditions and `&&` or `||` lists.
Check expected failures explicitly. Do not hide a failed assertion behind a successful final command.
Avoid `producer | grep -q pattern` under `pipefail` when an early reader exit can give the producer SIGPIPE.
Write output to a file, then check the file when that behavior matters.

## Test environments

| Stage | Available input | Purpose |
| --- | --- | --- |
| `build` | Source workspace and build tools | Upstream suites, compilation checks and staged hardening checks |
| `installed` | Selected RPM closure and explicit test tools | Runtime behavior and installed consumer interfaces |
| `transaction` | Private writable RPM root and supplied binary RPMs | Installation, upgrade, scriptlets, configuration and erase |

Output-level runtime tests select the named output and its declared runtime siblings.
Recipe-level runtime tests install all outputs. Use these for integration, not for minimal dependency checks.
Each runtime test has a fresh writable workspace and an empty `STAGE` directory.
Tests may reuse prepared root data. Writes to a workspace or transaction root must not affect another test.

Put test-only tools in `tests[].packages`. Build-stage test tools join the host build root, including for cross builds.
Installed-stage tools do not enter the build root or target sysroot.
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

Declare `files: tests`. rpmx copies regular files recursively and exposes the writable copy through `TEST_FILES`.
The recipe digest and SRPM include fixture contents. Fixture changes invalidate build-cache inputs.
Symlinks, parent traversal, missing directories and empty fixture directories are errors.
RPM fixtures under a recipe's `tests/` directory are trackable in Git.
Keep their source, checksums and signing-key provenance beside them.
Do not depend on executable permissions in the SRPM. Invoke shell fixtures with `bash -euo pipefail "$TEST_FILES/check.sh"`.
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
Full stdout and stderr remain in separate test log files. JUnit includes bounded output tails.

JSON results distinguish `passed`, `failed`, `error` and `skipped`.
Environment errors and missing input RPMs are not passes. A declared test that has not run is not a pass.
Record the RPM identity, architecture, rpmx revision and dependency-root evidence with the report.

Before release, run the full build and runtime tests on both supported architectures.
Check package combinations and upgrades in addition to isolated output tests.
Review every skip and failure. Passing tests establish the tested behavior in the recorded environment.
They do not prove that the package has no defects or security vulnerabilities.
