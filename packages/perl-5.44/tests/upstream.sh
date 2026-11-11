#!/usr/bin/env bash
set -euo pipefail

# Socket tests need deterministic loopback names in the offline build root.
# Supply them privately, keeping the sandbox's /etc and account lookup intact.
printf '127.0.0.1 localhost\n::1 localhost\n' > upstream-hosts
export NSS_WRAPPER_HOSTS="$PWD/upstream-hosts"
export LD_PRELOAD="$LIBDIR/libnss_wrapper.so"
[[ -r $LD_PRELOAD ]] || {
  echo "Perl upstream tests require NSS wrapper at $LD_PRELOAD" >&2
  exit 1
}
export LD_LIBRARY_PATH="$PWD${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
./perl -Ilib -MSocket=:all -e '
  my $address = gethostbyname("localhost");
  defined($address) && unpack("H*", $address) eq "7f000001"
    or die "Perl upstream tests require localhost to resolve to 127.0.0.1\n";
  my ($error, $host) = getnameinfo(pack_sockaddr_in(80, $address), NI_NUMERICSERV);
  !$error && $host eq "localhost"
    or die "Perl upstream tests require 127.0.0.1 to resolve to localhost\n";
'

# ExtUtils::Embed tests link -L.. -lperl. Configure builds the versioned
# library; its development symlink normally appears only during installation.
# The production payload is already staged, so this link serves this suite.
library=$(./perl -Ilib -MConfig -e 'print $Config{libperl}')
[[ -f $library ]] || {
  echo "Perl upstream tests cannot find the configured library: $library" >&2
  exit 1
}
ln -sfn "$library" libperl.so
make test TEST_JOBS=2 2>&1 | tee perl-test.log
grep -F 'All tests successful' perl-test.log
