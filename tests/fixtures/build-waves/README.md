# Dependency wave integration tests

Run on a native x86-64 or aarch64 Linux host with the pinned rpmx, rootless
Podman, Bubblewrap, Python with PyYAML, Git, `rpm2archive` and the RPM repository tools:

```sh
RUN_RPM_INTEGRATION=1 python3 -m unittest discover -s tests -p test_build_waves_integration.py -v
```

Set `RPMX` to select the rpmx executable. Set `RPM_WAVE_TEST_OUTPUT` to a new,
absolute directory to retain all evidence. Otherwise temporary files are
removed when the tests finish. Initial toolchain resolution needs the Fedora
44 repository and builder image. The RPM fixtures use temporary local
repositories and do not publish anything.

The test creates four recipes, A through D, from `main.c`. Each package ships
a static executable, a timestamp-bearing static archive, and a header.
B compiles against A's header, C against B,
and D against C. Each executable appends its own letter to the compiled marker
and writes that value into its exported header.

The baseline prints `old/a/b/c/d`. Changing only A's input must cause four
waves. D's installed test must print `new/a/b/c/d`. The tests also compare the
dependency lock checksums with the actual preceding wave's RPMs and verify
that every acceptance record names the final repository.

Negative cases cover unchanged public inputs, a failed build, failed installed
acceptance, and a dependency cycle that reaches the wave limit. A failure must
prevent candidate export. Another case rebuilds B using only its prepared
bundle and input archive in an empty cache, after removing the source-worker
repository and coordinator artifacts. The fast planner tests in `test_build_transaction.py`
also check that independent packages can share a wave and that cycles wait
for dependencies outside their cycle.

`scripts/build-waves.py` is the local entry point under test. It takes a
transaction file and artifact directories, builds until the dependency closure
settles, accepts the final repository, and exports the tested candidate. It
does not publish or call GitHub. `test-build-waves.yml` runs this suite natively
on both architectures. It checks the build behavior, not a hosted controller's
dispatch and artifact-transfer behavior. Those hosting checks belong beside
the Actions adapter so a future service can replace that adapter without
changing these tests.

The coordinator accepts an execution adapter with two operations:

- `build_wave(state_path)` reads the current snapshot and produces the source
  and binary artifact directories for every pending package.
- `accept(state_path, repository)` tests all final packages against the sealed
  repository and produces the accepted artifact directories.

Both operations return after all their work succeeds, or raise on failure.
`LocalExecutor` runs the commands directly. The Actions adapter resumes
from snapshots between dispatched runs and uses the same artifact layout.
It does not implement this blocking Python interface. GitHub run IDs,
tokens and artifact IDs belong in that adapter. They are not dependency-planner
inputs. `test_wave_executor.py` verifies that failed or incomplete adapters
cannot advance a transaction or reach acceptance.

The four-wave case also changes D on a new commit, reuses A/B/C byte for byte,
rebuilds only D, and accepts all four packages against the updated repository.
