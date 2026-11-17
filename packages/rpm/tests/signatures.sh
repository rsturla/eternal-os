#!/usr/bin/env bash
set -euo pipefail

# Keep all trust state private. Verify, but do not execute or install, the
# upstream x86_64 fixture: signature verification is independent of target ABI.
keyring="$PWD/openpgp-db"
package="$TEST_FILES/openpgp/hello-2.0-1.x86_64-signed.rpm"
rpm --dbpath "$keyring" --initdb
if rpmkeys --dbpath "$keyring" -Kv "$package" > untrusted.verify 2>&1; then
  echo 'RPM trusted a signed package without its public key' >&2
  exit 1
fi
grep -F 'NOKEY' untrusted.verify || {
  cat untrusted.verify >&2
  echo 'RPM must parse the signed fixture and report its missing public key' >&2
  exit 1
}

rpmkeys --dbpath "$keyring" --import "$TEST_FILES/openpgp/rpm.org-rsa-2048-test.pub"
rpmkeys --dbpath "$keyring" -Kv "$package" > trusted.verify 2>&1 || {
  cat trusted.verify >&2
  echo 'RPM rejected the correctly signed fixture after public-key import' >&2
  exit 1
}
grep -E 'Header OpenPGP .* signature.*: OK' trusted.verify
grep -F 'Payload SHA256 digest: OK' trusted.verify

# Byte 542 is the final RSA signature octet in this pinned fixture's header
# OpenPGP packet (tag 268, offset 256, length 287). Change only the signature,
# leaving the signed header and payload intact: this tests crypto verification.
cp "$package" tampered.rpm
original=$(od -An -tu1 -j 542 -N1 tampered.rpm)
printf -v octal '%03o' "$((original ^ 255))"
printf '%b' "\\$octal" | dd of=tampered.rpm bs=1 seek=542 conv=notrunc status=none
if rpmkeys --dbpath "$keyring" -Kv tampered.rpm > tampered.verify 2>&1; then
  echo 'RPM accepted a modified OpenPGP signature' >&2
  exit 1
fi
grep -E 'Header OpenPGP .* signature.*: BAD' tampered.verify
grep -F 'Header SHA256 digest: OK' tampered.verify
grep -F 'Payload SHA256 digest: OK' tampered.verify
