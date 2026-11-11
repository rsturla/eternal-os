# Go 1.26 packaging

This stream builds from the upstream source archive with Fedora 44's `golang`
compiler tools, requested explicitly as `golang-bin`. That package requires
Fedora's exact `go` version and release, so an Eternal selector cannot replace
the bootstrap compiler.

The implementation owns `go-1.26`, `gofmt-1.26` and its private tree at
`/usr/lib64/golang-1.26`. The optional `golang-1.26-default` output owns
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
6763fdaa373962399e8a3aff6e1fe863d3837579](https://gitlab.com/redhat/hummingbird/rpms/-/tree/6763fdaa373962399e8a3aff6e1fe863d3837579/rpms/golang1.26).
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
- [Wolfi Go recipe](https://github.com/wolfi-dev/os/blob/main/go-1.26.yaml)
- [Upstream FIPS documentation](https://go.dev/doc/security/fips140)
