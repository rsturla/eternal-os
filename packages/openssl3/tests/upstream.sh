#!/usr/bin/env bash
set -euo pipefail

# The minimal build root has no hosts database. OCSP/TLS tests connect to
# localhost, so supply loopback names privately without changing /etc/hosts.
printf '127.0.0.1 localhost\n::1 localhost\n' > upstream-hosts
export NSS_WRAPPER_HOSTS="$PWD/upstream-hosts"
export LD_PRELOAD="$LIBDIR/libnss_wrapper.so"
[[ -r $LD_PRELOAD ]] || {
  echo "OpenSSL upstream tests require NSS wrapper at $LD_PRELOAD" >&2
  exit 1
}
perl -MSocket -e '
  my $address = gethostbyname("localhost");
  defined($address) && unpack("H*", $address) eq "7f000001"
    or die "OpenSSL upstream tests require localhost to resolve to 127.0.0.1\n";
'
make test HARNESS_JOBS="$(nproc)"
