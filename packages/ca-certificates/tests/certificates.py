import glob
import pathlib
import ssl
import sys

if sys.argv[1] == "individual":
    paths = glob.glob("/usr/share/ca-certificates/mozilla/*.crt")
    assert len(paths) > 50, len(paths)
    configured = [
        line.strip()
        for line in pathlib.Path("/etc/ca-certificates.conf").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert configured
    actual = {
        str(pathlib.Path(path).relative_to("/usr/share/ca-certificates"))
        for path in paths
    }
    assert set(configured) == actual, (
        "certificate configuration does not match installed roots"
    )
    for path in paths:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=path)
        assert context.cert_store_stats()["x509_ca"] >= 1, path
else:
    paths = [
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-bundle.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ]
    data = pathlib.Path(paths[0]).read_bytes()
    assert data.count(b"-----BEGIN CERTIFICATE-----") > 50
    for path in paths:
        assert pathlib.Path(path).read_bytes() == data, path
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=path)
        assert context.cert_store_stats()["x509_ca"] > 50
