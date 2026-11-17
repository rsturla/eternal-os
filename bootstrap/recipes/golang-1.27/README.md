# Go 1.27 bootstrap variant

This variant preserves the Fedora `golang-bin` seed dependency.
The production recipe is `packages/golang-1.27/package.yaml`.
Both variants carry the same upstream sources, FIPS patches and build flags.
This variant tests co-installation with Fedora Go. Production tests use the
other Eternal stream instead.
Keep their source versions and patches in sync when you update a stream.
Stage selection and provider policy are in `bootstrap/bootstrap.yaml`.

The schema 2 recipe has the same three source suites and six installed cases
as the production recipe. External fixtures cover pure Go behavior, formatting,
compiler diagnostics, cgo, race detection, cross compilation, FIPS policy and
the default selector. The co-installation case explicitly invokes `/usr/bin/go`
from Fedora alongside the versioned candidate. Only that case adds the Fedora
compiler as an acceptance dependency; it does not change the other test roots.
Source suites retain JSON reports and run without external networking.
