# Go 1.26 bootstrap variant

This variant preserves the Fedora `golang-bin` seed dependency.
The production recipe is `packages/golang-1.26/package.yaml`.
Both variants carry the same upstream sources, FIPS patches and build flags.
This variant tests co-installation with Fedora Go. Production tests use the
other Eternal stream instead.
Keep their source versions and patches in sync when you update a stream.
Stage selection and provider policy are in `bootstrap/bootstrap.yaml`.
