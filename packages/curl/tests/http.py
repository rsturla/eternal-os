import pathlib
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

payload = bytes(range(256)) * 100


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/payload")
            self.end_headers()
            return
        if self.path != "/payload":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
url = "http://127.0.0.1:" + str(server.server_port)


def curl(*args):
    return subprocess.run(
        [
            "curl",
            "--noproxy",
            "*",
            "--silent",
            "--show-error",
            "--max-time",
            "10",
            *args,
        ],
        capture_output=True,
    )


try:
    r = curl("--fail", url + "/payload")
    assert r.returncode == 0 and r.stdout == payload, r.stderr
    r = curl("--fail", "--location", url + "/redirect")
    assert r.returncode == 0 and r.stdout == payload, r.stderr
    r = curl("--fail", url + "/missing")
    assert r.returncode == 22, r
    pathlib.Path("input").write_bytes(payload)
    r = curl("--fail", "--data-binary", "@input", url + "/post")
    assert r.returncode == 0 and r.stdout == payload, r.stderr
finally:
    server.shutdown()
    server.server_close()
    thread.join()

# Use a new self-signed certificate for this run. No external endpoint or
# machine trust settings are involved in the trust and hostname checks.
import ssl

subprocess.run(
    [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-noenc",
        "-config",
        "/dev/null",
        "-days",
        "1",
        "-keyout",
        "key.pem",
        "-out",
        "cert.pem",
        "-subj",
        "/CN=unrelated.invalid",
        "-addext",
        "subjectAltName=IP:127.0.0.1",
    ],
    check=True,
    stdout=subprocess.DEVNULL,
)
server = HTTPServer(("127.0.0.1", 0), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("cert.pem", "key.pem")
server.socket = context.wrap_socket(server.socket, server_side=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
url = "https://127.0.0.1:" + str(server.server_port)
try:
    r = curl("--fail", url + "/payload")
    assert r.returncode == 60, r
    r = curl("--fail", "--cacert", "cert.pem", url + "/payload")
    assert r.returncode == 0 and r.stdout == payload, r.stderr
    r = curl(
        "--fail",
        "--cacert",
        "cert.pem",
        "--resolve",
        "localhost:" + str(server.server_port) + ":127.0.0.1",
        "https://localhost:" + str(server.server_port) + "/payload",
    )
    assert r.returncode == 60, r
finally:
    server.shutdown()
    server.server_close()
    thread.join()
