# Signing

Eternal signs packages and repository metadata with OpenPGP. `rpmx` never
stores or discovers keys: every signing operation takes an explicit key file.
CI reads the key from repository secrets.

Signing is optional in the workflows so a fork builds immediately. A production
repository must be signed before it is announced.

## Generate a key

On a trusted machine:

```console
rpmx keygen --output eternal-signing-key.asc \
  --user-id "Eternal Linux <packages@eternal.sturla.tech>" \
  --bits 4096
```

This writes `eternal-signing-key.asc` and `eternal-signing-key.asc.pub`. Keep
the private file offline (password manager, HSM or an offline vault). Never
commit it.

## Configure the repository secrets

| Secret | Value |
| --- | --- |
| `RPMX_SIGNING_KEY` | ASCII-armored private key (`eternal-signing-key.asc`) |
| `RPMX_PUBLIC_KEY` | ASCII-armored public key (`eternal-signing-key.asc.pub`) |
| `PACKAGES_S3_ACCESS_KEY_ID` | S3-compatible access key ID (R2 access key) |
| `PACKAGES_S3_SECRET_ACCESS_KEY` | S3-compatible secret access key |

Add them under **Settings → Secrets and variables → Actions**. The release
workflow:

1. writes `RPMX_SIGNING_KEY` to a mode-0600 temporary file;
2. passes it to `rpmx build --signing-key` and `rpmx repo --signing-key`, then
   imports it into a temporary GnuPG keyring to sign the merged archive index;
3. publishes `RPMX_PUBLIC_KEY` as `RPM-GPG-KEY-eternal`;
4. writes `gpgcheck=1` into the published `eternal.repo`;
5. uploads `rolling` and the append-only `archive` repository to the bucket.

The bucket, endpoint and public URL are repository **variables**, not secrets:

| Variable | Value |
| --- | --- |
| `PACKAGES_S3_BUCKET` | Bucket name, for example `eternal-packages` |
| `PACKAGES_S3_ENDPOINT` | R2 endpoint, for example `https://<account>.r2.cloudflarestorage.com`; leave empty for AWS S3 |
| `PACKAGES_S3_REGION` | `auto` for R2, or the AWS region |
| `PACKAGES_BASE_URL` | Public repository base URL, for example `https://packages.eternal.sturla.tech` |

CI keys must not have a passphrase. Keep the passphrase-protected copy for
manual releases, or use `--signing-passphrase-env` locally.

The metadata merge uses an isolated temporary GnuPG keyring. Its signing key
must have no passphrase. The publisher verifies existing archive signatures
with the supplied private and public keys. Include the old public key during
rotation. A signed archive cannot receive an unsigned update.

## Sign locally

Use the same scripts and flags as CI:

```console
./scripts/build-all.sh --output out \
  --signing-key ~/eternal-signing-key.asc
./scripts/publish-repo.sh --packages out --output site --release rolling \
  --signing-key ~/eternal-signing-key.asc \
  --public-key ~/eternal-signing-key.asc.pub

```

To publish both channels locally, export `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` first (use `--endpoint-url` for R2):

```console
./scripts/publish-bucket.sh --packages out --output site \
  --bucket eternal-packages \
  --endpoint-url https://<account>.r2.cloudflarestorage.com \
  --base-url https://packages.eternal.sturla.tech \
  --signing-key ~/eternal-signing-key.asc \
  --public-key ~/eternal-signing-key.asc.pub
```

## Turn on verification in the image

Once the key is published, `packages/eternal-release/files/eternal.repo` must
verify packages:

```ini
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-eternal
```

The file system location must be provided by a package. Add
`packages/eternal-keys/`:

```console
mkdir -p packages/eternal-keys/files
cp eternal-signing-key.asc.pub \
   packages/eternal-keys/files/RPM-GPG-KEY-eternal
```

with a recipe that installs it to `/etc/pki/rpm-gpg/RPM-GPG-KEY-eternal`. Add
`eternal-keys` to `eternal-base` so the key is present in every image.

Then flip `gpgcheck=0` to `1` in the release package and rebuild.

## Verify manually

```console
rpm --import RPM-GPG-KEY-eternal
dnf --disablerepo='*' --enablerepo=eternal makecache
rpm -q --checksig packages/rolling/x86_64/eternal-release-*.rpm
rpmx repo --rpms out/x86_64 --output /tmp/verify \
  --signing-key eternal-signing-key.asc
```

A signed repository has `repodata/repomd.xml.asc` beside `repomd.xml`; dnf
rejects metadata whose signature does not verify.

## Rotation

1. Generate a new key.
2. Publish both public keys (as separate files in `eternal-keys`; dnf accepts
   multiple `gpgkey=` entries).
3. Re-sign the repository with the new key.
4. Update the `RPMX_*` secrets.
5. Keep the old public key for at least one release cycle so installed systems
   can verify cached metadata.
