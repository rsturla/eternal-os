# Update RPM repository metadata without a local mirror

This experiment works. A publisher needs the existing package metadata and the
new RPMs. It does not need the existing RPMs. RustFS served the repository over
HTTP, and dnf5 installed and upgraded packages from the result.

The Go prototype uses the AWS SDK for S3 operations. It calls `createrepo_c` to
read new RPMs and `mergerepo_c` to combine package metadata. It does not change
the release scripts or the pinned rpmx revision.

## Why this matters here

`scripts/publish-bucket.sh` downloads the complete archive before each metadata
refresh. Its network and disk use grow with historical RPM payloads.
`publish-repo.sh` then gives the complete package set to `rpmx repo`.

The archive can instead use this process:

```text
new RPMs or explicit incoming object keys
                  |
                  v
        createrepo_c on new RPMs
                  |
                  v
old repomd + primary/filelists/other ---> mergerepo_c --all --omit-baseurl
                                                    |
                                                    v
                                      upload immutable RPMs and metadata
                                                    |
                                                    v
                                      conditional PUT of repomd.xml
```

`createrepo_c --update` alone does not solve this. The experiment removes the
old local RPMs and confirms that `--update` removes their metadata entries.
`--update` reuses metadata for files that remain in its input tree.

`mergerepo_c` reads repository metadata. Its
[`--all` option](https://raw.githubusercontent.com/rpm-software-management/createrepo_c/master/doc/mergerepo_c.8)
retains different versions and releases. `--omit-baseurl` keeps relative package
URLs instead of adding the temporary `file://` input directories.

## Run the prototype

Requirements: Go 1.25 or later, `createrepo_c`, and `mergerepo_c`. The prototype
uses normal AWS SDK credential discovery. Configure credentials before use.
Use an unsigned test repository.

```sh
cd experiments/incremental-repodata
go build -o /tmp/repopush .

# Upload the RPM first. Use the same endpoint and credentials for both commands.
aws --endpoint-url http://127.0.0.1:9000 s3 cp new.rpm s3://test-packages/incoming/new.rpm

# Download only the new RPM and existing repository metadata, then publish.
/tmp/repopush --endpoint http://127.0.0.1:9000 \
  --bucket test-packages --prefix archive/x86_64 \
  --object incoming/new.rpm

# Alternatively, supply new local RPMs directly.
/tmp/repopush --endpoint http://127.0.0.1:9000 \
  --bucket test-packages --prefix archive/x86_64 new.rpm another.rpm
```

Repeat `--object` for a batch. Place flags before positional filenames.
The bucket must exist. Omit `--endpoint` for AWS S3. Use `--region` if required.
A missing index creates a repository. Permission errors do not create an empty
replacement repository. S3 can require `ListBucket` permission to distinguish
a missing key from a forbidden key.

The prototype downloads an incoming RPM once, then publishes its bytes under
`Packages/<sha256>.rpm`. It leaves the incoming object in place. This copy
proves the workflow without trusting mutable incoming filenames. A production
publisher can use server-side copy after it verifies the input object version.

## Publication and concurrent writers

1. Generate metadata from the new RPMs.
2. Upload the new RPMs under paths that include their checksums.
3. Read `repomd.xml` and save its ETag.
4. Download the three referenced metadata objects and verify their SHA-256 checksums.
5. Merge the old metadata with the new package metadata.
6. Upload checksum-named metadata objects.
7. Replace `repomd.xml` with `If-Match: <previous ETag>`.

For the first publication, use `If-None-Match: *`. If another publisher wins,
read its index and merge again. Retry at most five times. A failed attempt can
leave unreferenced objects, but it does not publish an incomplete index.
Keep old RPMs and metadata for clients that already read an earlier index.

These conditions follow the
[S3 conditional write model](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).
[Cloudflare R2 also documents conditional PutObject](https://developers.cloudflare.com/r2/api/s3/conditional-operations/).
R2 was not tested here.

The test uses one RustFS node. Its results do not establish correctness across
a distributed RustFS cluster. RustFS previously had a
[reported race across multiple endpoints](https://github.com/rustfs/rustfs/issues/1659).
The issue is closed. Test the deployed topology before concurrent production use.

## Evidence

The smoke test ran on 11 November 2026 with:

| Component | Version |
| --- | --- |
| RustFS | 1.0.5, image digest pinned in `smoke.py` |
| createrepo_c and mergerepo_c | 1.2.6 |
| Go | 1.27.4, module targets Go 1.25 |
| dnf5 client | 5.4.7.0 in the Fedora 44 container |

The fixture starts with `probe-core` version 1 and `probe-kept`. It adds
`probe-core` version 2 and `probe-addon`. The addon requires core version 2
and a file under `/opt` from the unchanged package. This exercises filelists.
The initial metadata uses simple filenames, to exercise migration to checksum-named metadata.

The updater host deletes the old RPMs before publication. An HTTP proxy rejects
historical RPM GETs from the updater. The dnf5 client uses RustFS directly so
it can download the packages it installs.

| Check | Result |
| --- | --- |
| Old repository downloads during the update | Four metadata objects, 2,690 bytes in the fixture |
| Historical RPM downloads by the updater | Zero |
| Incoming object downloads | One new RPM, 6,734 bytes in the fixture |
| Package retention | dnf5 sees both core versions and the unchanged package |
| Installation and upgrade | dnf5 installs the addon, upgrades core, and installs the unchanged file dependency |
| Old snapshot references | All old metadata objects still match their checksums |
| Concurrent first publication | One conditional create loses, retries, and preserves both packages |
| Concurrent existing repository updates | One stale ETag loses, retries, and preserves both deltas |
| Repeated input | No duplicate package record |
| Unknown metadata, corrupt checksum, existing signature | Publication stops; invalid metadata does not replace the index |

Fixture sizes demonstrate request behavior. They are not a large-repository benchmark.
Metadata download and rewrite cost still grows with the package count. The
prototype also buffers each object in memory. It avoids historical RPM transfer,
but it does not perform a constant-size metadata update.

Run the full experiment with Podman, AWS CLI, Python 3, and the build requirements:

```sh
python3 experiments/incremental-repodata/smoke.py
```

The script builds a Fedora test image, starts disposable RustFS storage, builds
four fixture RPMs, and runs dnf5 in an isolated install root. It removes the
RustFS container and leaves a local evidence directory with the update log and
installed files. It prints the path. Set `TMPDIR` and `GOCACHE` if needed.
Use `CGO_ENABLED=0 go vet ./...` within this directory for the Go checks.
The SDK dependencies are pinned in `go.mod` and `go.sum`.

## What to build for Eternal

Start with an explicit publisher invocation from CI. Upload new RPMs to an
incoming prefix, then pass their keys as a batch. Bucket events can later feed
a queue. Deduplicate events, pin incoming object versions, and batch updates.
Avoid a metadata rewrite for each RPM in a large build.

Replace the archive download loop with a metadata import and merge. Preserve
separate repositories for each architecture and `SRPMS`. Serialize the transition
from the current publisher, since its unconditional PUT can bypass this
prototype's ETag checks.

Rolling needs an explicit package-set policy. The archive retains historical
versions. Rolling must also remove withdrawn packages and obsolete subpackages.
A manifest of the intended rolling set can select records from old metadata
and new RPMs without old payloads. A name-and-architecture replacement rule
alone cannot remove a subpackage that a new build stops producing.

Before production integration:

- Add signature verification and signing. Publish a matching index and detached
  signature. Two independent S3 keys do not provide an atomic switch. Consider
  immutable signed snapshot directories with an HTTP routing pointer, or define
  and test a client retry policy for the two-file transition.
- Preserve repository policy metadata such as updateinfo, comps, and modules.
  The prototype rejects these types. SQLite and zchunk caches can be omitted
  or regenerated.
- Reject different RPM bytes with an existing NEVRA. Define epoch handling and
  replacement policy explicitly. `mergerepo_c --all` is not a release manifest.
- Verify incoming RPM signatures and architecture. Add object size limits,
  bounded streaming, request deadlines, and retry backoff.
- Define snapshot retention and garbage collection. Never delete objects that
  an active client snapshot can still reference.
- Test failures between uploads and the index PUT, and test the production
  storage topology and CDN cache behavior.

Go is sufficient for the S3 publisher. A Rust integration can instead
extend Rust rpmx with metadata import and package selection. The
[`rpmrepo_metadata` crate](https://docs.rs/rpmrepo_metadata/latest/rpmrepo_metadata/)
has readers and writers for repository metadata, including streaming package
iteration. That would remove the external merge commands and reuse rpmx's RPM
reader and signing code. This experiment does not validate that crate.

The useful interface is an old metadata snapshot plus new RPMs and a package-set
policy. Storage publication stays separate from metadata generation. The same
generator can then serve local tests, CI, and an event-driven publisher.
