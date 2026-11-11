These public verification fixtures are copied unchanged from RPM 6.1.0's
tag `rpm-6.1.0-release`, commit
`f832c7e69945248dd5bcfcacfd10c176ee300fa2`:

- Signed RPM: [tests/data/RPMS/hello-2.0-1.x86_64-signed.rpm](https://github.com/rpm-software-management/rpm/blob/f832c7e69945248dd5bcfcacfd10c176ee300fa2/tests/data/RPMS/hello-2.0-1.x86_64-signed.rpm)
- Public key: [tests/data/keys/rpm.org-rsa-2048-test.pub](https://github.com/rpm-software-management/rpm/blob/f832c7e69945248dd5bcfcacfd10c176ee300fa2/tests/data/keys/rpm.org-rsa-2048-test.pub)

The matching source archive is already pinned by this recipe. The public key
fingerprint is `771B18D3D7BAA28734333C424344591E1964C5FC`. No private key is
included. The signed RPM is never installed or executed; both architectures
verify the same bytes. Upstream distributes these fixtures under its COPYING
terms.

SHA256:

- `hello-2.0-1.x86_64-signed.rpm`: `d32735351a8952afc9e4afd7309e3a1929288eff5af32526934314f1f304ff7f`
- `rpm.org-rsa-2048-test.pub`: `0a2f43cf43e170f9c42a62c329641945111fb535b137c1b746ec5e24307179b1`

The signature corruption control changes byte 542, the last octet of the
header RSA OpenPGP signature (signature-header tag 268, binary data beginning
at file offset 256, length 287). Header and payload SHA256 digests must still
verify, so rejecting this fixture specifically exercises signature checking.
