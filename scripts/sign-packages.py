#!/usr/bin/env python3
"""Sign tested RPM envelopes and prove their main headers and payloads stayed exact."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def content_digest(path):
    """Hash the RPM main header and compressed payload, excluding lead/signature."""
    with path.open('rb') as stream:
        lead = stream.read(96)
        signature = stream.read(16)
        if (len(lead) != 96 or lead[:4] != b'\xed\xab\xee\xdb' or
                len(signature) != 16 or signature[:8] != b'\x8e\xad\xe8\x01\x00\x00\x00\x00'):
            raise ValueError(f'invalid RPM envelope: {path}')
        entries, size = struct.unpack('>II', signature[8:])
        offset = (96 + 16 + entries * 16 + size + 7) // 8 * 8
        if offset + 16 > os.fstat(stream.fileno()).st_size:
            raise ValueError(f'truncated RPM signature: {path}')
        stream.seek(offset)
        if stream.read(8) != b'\x8e\xad\xe8\x01\x00\x00\x00\x00':
            raise ValueError(f'invalid RPM main header: {path}')
        stream.seek(offset)
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sign(directory, key, rpmx='rpmx'):
    paths = sorted(directory.rglob('*.rpm'))
    if not paths:
        raise ValueError('no tested RPMs to sign')
    records = {}
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'invalid staged RPM: {path}')
        relative = path.relative_to(directory).as_posix()
        before = content_digest(path)
        records[relative] = {'tested_sha256': digest(path), 'content_sha256': before}
        subprocess.run([rpmx, 'sign', '--signing-key', str(key), str(path)], check=True)
        if content_digest(path) != before:
            raise ValueError(f'signing changed a tested header or payload: {path}')
        records[relative]['signed_sha256'] = digest(path)
    # These records describe the tested unsigned artifacts. Keep their original
    # identities and record signed envelope identities in a separate receipt.
    (directory / 'signing.json').write_text(json.dumps({'schema': 1, 'rpms': records}, sort_keys=True, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--signing-key', type=Path, required=True)
    parser.add_argument('--rpmx', default=os.environ.get('RPMX', 'rpmx'))
    args = parser.parse_args()
    sign(args.directory, args.signing_key, args.rpmx)


if __name__ == '__main__':
    main()
