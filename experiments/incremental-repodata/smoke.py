#!/usr/bin/env python3
"""Exercise repopush against disposable RustFS storage and real dnf5 clients.

Requires Go, Podman, AWS CLI, Python 3, createrepo_c and mergerepo_c.
Creates only a disposable local bucket. Set TMPDIR if /tmp has a small quota.
"""
import concurrent.futures
import gzip
import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
RUSTFS = "docker.io/rustfs/rustfs@sha256:b81d16a90ee25bd9511280127ca1471788c6e874cf0f0da759645f46b2dc1d74"
BUILDER = "localhost/eternal-repodata-test"
BUCKET = "repodata-test"
ENV = dict(os.environ, AWS_ACCESS_KEY_ID="repodata-test",
           AWS_SECRET_ACCESS_KEY="repodata-test-secret", AWS_DEFAULT_REGION="us-east-1",
           AWS_EC2_METADATA_DISABLED="true", AWS_REQUEST_CHECKSUM_CALCULATION="when_required",
           AWS_RESPONSE_CHECKSUM_VALIDATION="when_required", CGO_ENABLED="0")


def run(*args, ok=True, **kwargs):
    result = subprocess.run([str(x) for x in args], env=ENV, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    if ok and result.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))}\n{result.stdout}")
    return result


def main(work):
    run("podman", "build", "-q", "-t", BUILDER, "-f", HERE / "Containerfile.test", HERE)
    print(run("go", "version").stdout.strip(), flush=True)
    print(run("createrepo_c", "--version").stdout.strip(), flush=True)
    print(run("podman", "run", "--rm", BUILDER, "dnf5", "--version").stdout.splitlines()[0], flush=True)
    run("go", "build", "-o", work / "repopush", ".", cwd=HERE)
    container = "repodata-" + uuid.uuid4().hex[:12]
    run("podman", "run", "-d", "--name", container, "-p", "127.0.0.1::9000",
        "-e", "RUSTFS_ACCESS_KEY=repodata-test", "-e", "RUSTFS_SECRET_KEY=repodata-test-secret",
        "-e", "RUSTFS_CONSOLE_ENABLE=false", RUSTFS, "/data")
    try:
        port = run("podman", "port", container, "9000/tcp").stdout.strip().rsplit(":", 1)[1]
        endpoint = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                urllib.request.urlopen(endpoint + "/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("RustFS did not start")
        exercise(work, endpoint)
    finally:
        run("podman", "rm", "-f", container, ok=False)


def exercise(work, endpoint):
    def aws(*args, ok=True):
        return run("aws", "--endpoint-url", endpoint, "s3api", *args, ok=ok)

    aws("create-bucket", "--bucket", BUCKET)
    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*",
              "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{BUCKET}/*"}]}
    aws("put-bucket-policy", "--bucket", BUCKET, "--policy", json.dumps(policy))
    # Test conditions directly, independently of publisher retry behavior.
    probe = work / "probe"
    probe.write_text("one")
    first = json.loads(aws("put-object", "--bucket", BUCKET, "--key", "cas-probe",
                          "--body", probe, "--if-none-match", "*").stdout)
    assert aws("put-object", "--bucket", BUCKET, "--key", "cas-probe", "--body", probe,
               "--if-none-match", "*", ok=False).returncode
    probe.write_text("two")
    aws("put-object", "--bucket", BUCKET, "--key", "cas-probe", "--body", probe,
        "--if-match", first["ETag"])
    stale = aws("put-object", "--bucket", BUCKET, "--key", "cas-probe", "--body", probe,
                "--if-match", first["ETag"], ok=False)
    assert stale.returncode and "PreconditionFailed" in stale.stdout, stale.stdout
    print("PASS RustFS rejects duplicate create and stale ETag writes", flush=True)

    specs = work / "specs"
    specs.mkdir()
    for name, version, requires, file in [
        ("probe-core", "1", "", "/opt/repopush/core"),
        ("probe-core", "2", "", "/opt/repopush/core"),
        ("probe-kept", "1", "", "/opt/repopush/kept"),
        ("probe-addon", "1", "Requires: probe-core >= 2\nRequires: /opt/repopush/kept", "/opt/repopush/addon"),
    ]:
        spec = f"""Name: {name}
Version: {version}
Release: 1
Summary: Incremental repository test fixture
License: MIT
BuildArch: noarch
{requires}
%description
Disposable repository fixture.
%install
mkdir -p %{{buildroot}}/opt/repopush
printf '%s\\n' '{version}' > %{{buildroot}}{file}
%files
{file}
%changelog
* Wed Nov 11 2026 Repository test <test@example.invalid> - {version}-1
- Build fixture
"""
        (specs / f"{name}-{version}.spec").write_text(spec)
    run("podman", "run", "--rm", "-v", f"{work}:/work:Z", BUILDER, "sh", "-ec",
        'for s in /work/specs/*.spec; do rpmbuild -bb --define "_topdir /work/rpmbuild" "$s"; done')
    rpms = work / "rpmbuild/RPMS/noarch"
    core1, core2, kept, addon = [rpms / f"{n}.noarch.rpm" for n in
                               ["probe-core-1-1", "probe-core-2-1", "probe-kept-1-1", "probe-addon-1-1"]]
    seed = work / "seed"
    seed.mkdir()
    for rpm in [core1, kept]:
        shutil.copy(rpm, seed)
    # Match rpmx's current simple metadata names to exercise migration, too.
    run("createrepo_c", "--no-database", "--general-compress-type=gz", "--simple-md-filenames", seed)
    for f in seed.rglob("*"):
        if f.is_file():
            aws("put-object", "--bucket", BUCKET, "--key", "archive/x86_64/" + f.relative_to(seed).as_posix(), "--body", f)
    old_index = (seed / "repodata/repomd.xml").read_bytes()
    # Show that --update alone does not retain absent RPMs.
    (seed / core1.name).unlink()
    (seed / kept.name).unlink()
    run("createrepo_c", "--update", "--no-database", "--general-compress-type=gz", seed)
    primary = ET.parse(seed / "repodata/repomd.xml").find("{*}data[@type='primary']/{*}location").attrib["href"]
    assert len(ET.fromstring(gzip.decompress((seed / primary).read_bytes()))) == 0
    shutil.rmtree(seed)

    def dnf(*args):
        return run("podman", "run", "--rm", "--network", "host", "-v", f"{work}:/work:Z", BUILDER,
                   "dnf5", "-y", "--installroot=/work/root", "--releasever=44", "--no-gpgchecks",
                   "--disable-repo=*", f"--repofrompath=probe,{endpoint}/{BUCKET}/archive/x86_64",
                   "--setopt=probe.skip_if_unavailable=0", "--setopt=probe.metadata_expire=0",
                   "--setopt=optional_metadata_types=filelists",
                   "--refresh", *args).stdout

    dnf("install", "probe-core-1-1")
    # Delete every old fixture RPM. Only new inputs remain on the updater host.
    core1.unlink()
    kept.unlink()
    aws("put-object", "--bucket", BUCKET, "--key", "incoming/core2.rpm", "--body", core2)
    core2.unlink()

    # Observe actual S3 requests and block any attempt to fetch historical RPMs.
    requests = []
    barrier = threading.Barrier(2)
    gate = {"enabled": False, "count": 0}
    lock = threading.Lock()
    target_port = int(endpoint.rsplit(":", 1)[1])

    class Proxy(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def forward(self):
            object_path = self.path.split("?", 1)[0]
            with lock:
                requests.append((self.command, object_path))
                wait = (gate["enabled"] and self.command == "PUT"
                        and object_path.endswith("/repodata/repomd.xml") and gate["count"] < 2)
                if wait:
                    gate["count"] += 1
            if self.command == "GET" and object_path.endswith(".rpm") and "/incoming/" not in object_path:
                self.send_error(403, "Historical RPM download forbidden")
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if wait:
                barrier.wait(timeout=30)
            conn = http.client.HTTPConnection("127.0.0.1", target_port, timeout=60)
            conn.request(self.command, self.path, body=body, headers=dict(self.headers))
            response = conn.getresponse()
            content = response.read()
            self.send_response(response.status)
            for key, val in response.getheaders():
                if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                    self.send_header(key, val)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)
            conn.close()

        do_GET = do_HEAD = do_PUT = forward

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy = f"http://127.0.0.1:{server.server_port}"

    def push(*args, ok=True):
        return run(work / "repopush", "--endpoint", proxy, "--bucket", BUCKET, *args, ok=ok)

    try:
        updated = push("--object", "incoming/core2.rpm", addon)
        (work / "update.log").write_text(updated.stdout)
        gets = [p for method, p in requests if method == "GET"]
        assert len(gets) == 5, gets
        assert sum(p.endswith(".rpm") for p in gets) == 1, gets
        print("PASS update fetched one incoming RPM and four metadata objects; no historical RPMs", flush=True)
        available = dnf("repoquery", "--queryformat=%{name}-%{version}-%{release}.%{arch}\n")
        for package in ["probe-core-1-1.noarch", "probe-core-2-1.noarch", "probe-kept-1-1.noarch", "probe-addon-1-1.noarch"]:
            assert package in available, available
        dnf("install", "probe-addon")
        assert (work / "root/opt/repopush/core").read_text().strip() == "2"
        assert (work / "root/opt/repopush/kept").exists()
        print("PASS dnf5 retains old versions and upgrades core while resolving a file dependency from kept", flush=True)
        for rec in ET.fromstring(old_index).findall("{*}data"):
            data = urllib.request.urlopen(f"{endpoint}/{BUCKET}/archive/x86_64/" + rec.find("{*}location").attrib["href"]).read()
            assert hashlib.sha256(data).hexdigest() == rec.find("{*}checksum").text
        print("PASS metadata referenced by the previous index remains readable", flush=True)
        # Competing writers publish distinct packages from the same empty snapshot.
        gate["enabled"] = True
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            # Fetch two explicit inputs for a separate first-publication race.
            aws("get-object", "--bucket", BUCKET, "--key", "archive/x86_64/probe-core-1-1.noarch.rpm", work / "race-core.rpm")
            aws("get-object", "--bucket", BUCKET, "--key", "archive/x86_64/probe-kept-1-1.noarch.rpm", work / "race-kept.rpm")
            # Empty prefix forces both first publications to use If-None-Match.
            results = list(pool.map(lambda f: push("--prefix", "race/x86_64", f), [work / "race-core.rpm", work / "race-kept.rpm"]))
        assert any("re-read and merge again" in r.stdout for r in results), [r.stdout for r in results]
        race_index = ET.fromstring(urllib.request.urlopen(f"{endpoint}/{BUCKET}/race/x86_64/repodata/repomd.xml").read())
        href = race_index.find("{*}data[@type='primary']/{*}location").attrib["href"]
        primary = gzip.decompress(urllib.request.urlopen(f"{endpoint}/{BUCKET}/race/x86_64/{href}").read())
        assert len(ET.fromstring(primary)) == 2, primary
        print("PASS concurrent first publishers retry the merge and retain both packages", flush=True)
        gate["count"] = 0
        barrier.reset()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(push, "--prefix", "race/x86_64", "--object", "incoming/core2.rpm"),
                       pool.submit(push, "--prefix", "race/x86_64", addon)]
            results = [f.result() for f in futures]
        assert any("re-read and merge again" in r.stdout for r in results), [r.stdout for r in results]
        race_index = ET.fromstring(urllib.request.urlopen(f"{endpoint}/{BUCKET}/race/x86_64/repodata/repomd.xml").read())
        href = race_index.find("{*}data[@type='primary']/{*}location").attrib["href"]
        primary = gzip.decompress(urllib.request.urlopen(f"{endpoint}/{BUCKET}/race/x86_64/{href}").read())
        assert len(ET.fromstring(primary)) == 4, primary
        gate["enabled"] = False
        print("PASS concurrent updates retry stale ETags and retain both deltas", flush=True)
        repeated = push(addon)
        assert repeated.returncode == 0
        index_url = f"{endpoint}/{BUCKET}/archive/x86_64/repodata/repomd.xml"
        repeated_index = ET.fromstring(urllib.request.urlopen(index_url).read())
        href = repeated_index.find("{*}data[@type='primary']/{*}location").attrib["href"]
        primary = gzip.decompress(urllib.request.urlopen(f"{endpoint}/{BUCKET}/archive/x86_64/{href}").read())
        assert len(ET.fromstring(primary)) == 4, primary
        print("PASS repeated input does not duplicate package records", flush=True)
        # Refuse silently dropping repository policy metadata.
        current = urllib.request.urlopen(f"{endpoint}/{BUCKET}/archive/x86_64/repodata/repomd.xml").read()
        bad = work / "unsupported.xml"
        bad.write_bytes(current.replace(b"</repomd>", b'<data type="modules"/></repomd>'))
        aws("put-object", "--bucket", BUCKET, "--key", "archive/x86_64/repodata/repomd.xml", "--body", bad)
        failed = push(addon, ok=False)
        assert failed.returncode and 'unsupported metadata "modules"' in failed.stdout, failed.stdout
        assert urllib.request.urlopen(index_url).read() == bad.read_bytes()
        print("PASS unsupported metadata aborts publication without replacing the index", flush=True)
        broken = current.replace(b'<checksum type="sha256">', b'<checksum type="sha256">0', 1)
        bad.write_bytes(broken)
        aws("put-object", "--bucket", BUCKET, "--key", "archive/x86_64/repodata/repomd.xml", "--body", bad)
        failed = push(addon, ok=False)
        assert failed.returncode and "incorrect checksum" in failed.stdout, failed.stdout
        assert urllib.request.urlopen(index_url).read() == broken
        print("PASS checksum corruption aborts publication without replacing the index", flush=True)
        aws("put-object", "--bucket", BUCKET, "--key", "archive/x86_64/repodata/repomd.xml.asc", "--body", probe)
        failed = push(addon, ok=False)
        assert failed.returncode and "signed repository unsupported" in failed.stdout, failed.stdout
        print("PASS signed repository is refused", flush=True)
    finally:
        server.shutdown()
        server.server_close()
    print(f"Evidence saved in {work}", flush=True)


if __name__ == "__main__":
    # Keep evidence after success or failure; the disposable RustFS server is removed.
    workspace = Path(tempfile.mkdtemp(prefix="repodata-smoke-")).resolve()
    print(f"Working directory: {workspace}", flush=True)
    main(workspace)
