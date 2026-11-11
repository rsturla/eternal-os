# Go 1.27 packaging

This stream builds from the upstream source archive with Fedora 44's `golang`
compiler tools, requested explicitly as `golang-bin`. That package requires
Fedora's exact `go` version and release, so an Eternal selector cannot replace
the bootstrap compiler.

The implementation owns `go-1.27`, `gofmt-1.27` and its private tree at
`/usr/lib64/golang-1.27`. The optional `golang-1.27-default` output owns
`go` and `gofmt`. The two streams can coexist without their selectors.

## Build settings

Like Wolfi, the compiler targets x86-64-v2 and ARMv8.0 and uses
`GOTOOLCHAIN=local`. Like Fedora, it enables cgo and uses the system GCC.
Eternal's compiler wrapper applies the distribution C compiler flags.
The final Go tools use PIE, trim source paths and carry GNU build IDs.
Go strips the final tools at link time. The prebuilt source objects stay
unchanged.
No shared standard library is built because it conflicts with the certified
FIPS snapshot. No separate race library is needed with Go's build cache. The packaged race
and BoringCrypto objects target the native Linux architecture. Pure-Go
cross-compilation remains available.

## Native FIPS policy

The patches come unchanged from [Hummingbird rpms at
6763fdaa373962399e8a3aff6e1fe863d3837579](https://gitlab.com/redhat/hummingbird/rpms/-/tree/6763fdaa373962399e8a3aff6e1fe863d3837579/rpms/golang1.27).
Their headers identify the original golang-fips patches and commit.

`GOFIPS140=certified` selects the upstream certified snapshot by default.
The upstream `lib/fips140` archives stay unchanged. Built programs default to
`GODEBUG=fips140=auto`, which activates FIPS mode when the Linux host reports
`/proc/sys/crypto/fips_enabled=1`. Users can select another module with
`GOFIPS140` or change runtime mode with `GODEBUG=fips140`.

`GOEXPERIMENT=strictfipsruntime` or `-tags=strictfipsruntime` adds an optional
startup guard. It exits if the host requires FIPS and runtime FIPS mode is off.
The guard checks activation, not snapshot identity. The patches also provide
`GOLANG_NATIVE_HOSTFIPS_OVERRIDE=1` for tests without a FIPS host.

These settings do not certify Eternal or its binaries. Certification also
depends on the module's security policy and approved operating environment.
Installed tests check snapshot selection, host activation, explicit overrides
and both guard options. Build tests cover the patched dependency rules and TLS.

References:

- [Fedora Go recipe](https://src.fedoraproject.org/rpms/golang/blob/f44/f/golang.spec)
- [Wolfi Go recipe](https://github.com/wolfi-dev/os/blob/main/go-1.27.yaml)
- [Upstream FIPS documentation](https://go.dev/doc/security/fips140)

## Tests

The runtime tests compile and execute a module through the versioned commands,
check generic code, sorting, filesystem errors, compression errors and goroutine
synchronization, and reject invalid source and an invalid Printf call. This
case has no C compiler dependency. Formatting is compared with a fixed expected
file. A separate case installs GCC for cgo, runs the same module with the race
detector, and requires an intentional race to produce exit 66 and its diagnostic.
Pure-Go cross builds check both architecture settings in binary build metadata.
The default selector compiles a consumer through the unversioned commands in
its own dependency closure. Fedora coinstallation is a separate case.

The FIPS case checks the complete SHA256 known-answer value, authenticated
AES-GCM round trips and rejection of a modified tag. It preserves the snapshot,
host-auto, explicit override and both strict startup-guard checks. The strict
negative requires exit 1 and the exact guard message. These tests check the
packaging policy; they do not establish FIPS certification.

`build.tests` retains the upstream FIPS dependency and certified TLS suites and
adds short standard-library suites and requires evidence of executed passing
tests. Installed cases disable module downloads, use private writable Go caches
and retain reports. The runner keeps external networking disabled. Installed
hardening checks remain separate from the source suites. Run the shared build and acceptance
entry points described in [the testing guide](../../docs/testing.md).

Test references:

- [Go command and module behavior](https://pkg.go.dev/cmd/go)
- [Race detector options and diagnostics](https://go.dev/doc/articles/race_detector)
- [Native FIPS mode and snapshot policy](https://go.dev/doc/security/fips140)
