#!/usr/bin/env python3
"""Convert Mozilla NSS certdata.txt into individual PEM certificates.

Usage: extract-certs.py CERTDATA CERTDIR BUNDLE

Writes the PEM files into CERTDIR and the concatenated bundle into BUNDLE.
Prints the relative certificate paths, one per line, for
/etc/ca-certificates.conf.

Only certificates trusted for TLS server authentication (the Mozilla
SERVER_AUTH / TRUSTED_DELEGATOR combination) are emitted. Explicitly
distrusted roots are skipped.
"""

import base64
import os
import re
import sys
import textwrap


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2

    certdata, certdir, bundle = sys.argv[1:4]
    certs = []
    current = None
    in_value = False

    def flush():
        nonlocal current
        if current and current["label"] and current["der"] and current["trusted"]:
            if "distrust" not in current["label"].lower():
                certs.append((current["label"], current["der"]))
        current = None

    with open(certdata, "r", encoding="utf-8", errors="replace") as source:
        for raw in source:
            line = raw.rstrip("\n")

            if line.startswith("CKA_CLASS CK_OBJECT_CLASS CKO_CERTIFICATE"):
                flush()
                current = {"label": "", "der": b"", "trusted": False}
                in_value = False
                continue

            if current is None:
                continue

            if in_value:
                if line == "END":
                    in_value = False
                else:
                    current["der"] += bytes(
                        int(octet, 8) for octet in re.findall(r"\\([0-7]{3})", line)
                    )
                continue

            if line.startswith("CKA_LABEL UTF8 ") and not current["label"]:
                match = re.match(r'CKA_LABEL UTF8 "(.*)"$', line)
                if match:
                    current["label"] = match.group(1)
            elif line.startswith("CKA_VALUE MULTILINE_OCTAL"):
                in_value = True
            elif line.startswith(
                "CKA_TRUST_SERVER_AUTH CK_TRUST CKT_NSS_TRUSTED_DELEGATOR"
            ):
                current["trusted"] = True
            elif line.startswith(
                "CKA_TRUST_SERVER_AUTH CK_TRUST CKT_NSS_NOT_TRUSTED"
            ):
                current["trusted"] = False

    flush()

    os.makedirs(certdir, exist_ok=True)
    os.makedirs(os.path.dirname(bundle), exist_ok=True)

    used = set()
    config = []
    pem_parts = []

    for label, der in certs:
        name = label.translate(str.maketrans("/ (),", "__==_"))
        candidate = name
        suffix = 2
        while candidate in used:
            candidate = f"{name}-{suffix}"
            suffix += 1
        used.add(candidate)

        body = base64.b64encode(der).decode("ascii")
        pem = (
            "-----BEGIN CERTIFICATE-----\n"
            + "\n".join(textwrap.wrap(body, 64))
            + "\n-----END CERTIFICATE-----\n"
        )

        path = os.path.join(certdir, f"{candidate}.crt")
        with open(path, "w", encoding="ascii") as output:
            output.write(pem)
        config.append(f"mozilla/{candidate}.crt")
        pem_parts.append(pem)

    with open(bundle, "w", encoding="ascii") as output:
        output.write("\n".join(part.rstrip("\n") for part in pem_parts))
        output.write("\n")

    for line in config:
        print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
