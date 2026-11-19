# Removing Fedora from build roots

The minimal native build root and a recipe's complete build root are different
package sets. Audit both. A profile can resolve entirely from Eternal while a
recipe still adds Fedora tools or development libraries.

## Tools adoption

The native and distribution profiles now exclude Fedora providers for these
published Eternal source packages:

- bison, bzip2, expat, file and flex;
- json-c, libunistring, m4, ninja and popt;
- readline, scdoc, sqlite and tzdata.

The Python seed profile also adopts Eternal bzip2. Rebuilt Eternal interpreters
require its upstream `libbz2.so.1.0` SONAME. Its tested `libbz2.so.1` alias
supports the Fedora seed interpreter in the same root. Keep this runtime
available while the remaining Python seed dependencies stay separate.

Keep each library's runtime and development outputs together. The `file`
exclusions use `file` and `file-*` so that they do not exclude `filesystem`.
Use Eternal's existing package names and capability providers. Adoption does
not require renaming recipes to match Fedora.

Local resolution on 2026-11-19 compared main at `230651f9` with this batch:

| x86_64 package set | Packages before | Fedora before | Packages after | Fedora after |
| --- | ---: | ---: | ---: | ---: |
| Minimal native profile | 44 | 0 | 44 | 0 |
| RPM build dependencies | 119 | 54 | 118 | 40 |
| DNF5 build dependencies | 164 | 85 | 164 | 70 |

The proposed roots also resolve on aarch64: RPM has 118 packages, including
40 Fedora packages, and DNF5 has 164 packages, including 70 Fedora packages.
These measurements include transitive dependencies and
disable weak dependencies. They exclude optional test dependencies and the
builder image. Live repositories can change these counts.

Flex also builds locally with 48 Eternal input RPMs. Its complete input set
resolves with the Fedora repositories removed. The consumed input checksums
match that Eternal-only root lock. Explicit M4 provider exclusions prevent a
Fedora RPM release from winning over the published Eternal package.

The native profile still permits Fedora for dependencies outside this batch.
Do not interpret a successful resolution as proof of a Fedora-free recipe.
Check each locked package's repository origin. For a completed build,
`rpmx provenance <binary.rpm>` exposes the exact consumed build inputs.

## Build support adoption

The next batch selects published Eternal CMake, jsoncpp, libuv, rhash and
util-linux. It adopts util-linux's command, runtime and development outputs
together. The existing development package provides the individual library
development capabilities; it does not need Fedora's subpackage layout.

Local resolution compares published main at `e3325be4` with this batch:

| x86_64 package set | Packages before | Fedora before | Packages after | Fedora after |
| --- | ---: | ---: | ---: | ---: |
| DNF5 build dependencies | 164 | 70 | 161 | 57 |
| GLib build dependencies | 77 | 18 | 78 | 13 |

The proposed roots resolve on aarch64 with the same counts. GLib's development
dependency now installs the matching Eternal util-linux library group, so its
total package count increases while its Fedora count falls.

Fedora's directory-only `cmake-filesystem` package remains available. The seed
curl development stack still pulls libssh headers that require that exact
capability. CMake's executable, data and JSON library come from Eternal. Remove
the directory package with the curl development stack, rather than adding an
Eternal package solely to reproduce the seed layout.

Jsoncpp and GLib rebuild locally with the proposed profile. Jsoncpp's upstream
tests and both packages' installed acceptance tests pass. A util-linux
development consumer compiles and exercises all five libraries together.

## Next batches

1. Adopt the remaining published build tools and libraries in dependency
   groups. Next, adopt GLib, Meson and remaining headers such as toml11.
   Check all runtime and development
   providers before excluding the seed family.
2. Resolve the network stack together: CA certificates, OpenSSL, curl and
   nghttp2. Prefer Eternal's existing minimal feature sets. Rebuild consumers
   when an interface changes. Coordinate with the OpenSSL stream work.
3. Move normal Python builds onto the adopted native toolchain. Replace
   Meson's Fedora Python frontend and backend requests with versioned Eternal
   packages. Keep all supported interpreter matrix cells. Retain an explicit
   seed path for new interpreter releases until its replacement is proven.
4. Audit the remaining Fedora closure again. Add missing source recipes only
   for required features. For example, account and network configuration data
   currently supplied by `setup` needs an explicit Eternal owner. Do not copy
   a Fedora dependency tree into Eternal merely to satisfy seed packages.
5. Add a final acceptance run with all Fedora repositories disabled. Require
   every normal build and installed-package test root to resolve from Eternal
   on both architectures. Keep initial bootstrap stages explicit and separate.

The compiler-policy seed profile and the Fedora builder image are separate
remaining dependencies. Replacing recipe RPMs does not replace the resolver
image. Remove that image dependency after Eternal supplies the required
resolver tools and their runtime closure.

## Validation for each batch

Resolve representative recipe roots before and after the profile change.
Include package-manager consumers, build tools and every affected architecture.
Record origins from root locks, rather than estimating adoption from recipe
names or version suffixes.

Build consumers locally with the proposed profile. Then run
`scripts/accept-rpms.py` on those exact RPMs with the distribution profile.
Package compilation and installed-package acceptance are separate operations.
Keep local root locks and reports as validation artifacts; do not commit
floating repository locks as permanent package inputs.

Use the dependency-wave and candidate-promotion pipeline for hosted validation.
Publish the tested batch before starting a dependent adoption batch. This
avoids stacked profile changes and repeated builds against an unpublished set.
