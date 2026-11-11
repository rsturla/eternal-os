#!/usr/bin/env python3
"""List or verify the current snapshot's local metadata files."""

import argparse
import hashlib
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def metadata_files(index):
    root = ET.parse(index).getroot()
    if root.tag != '{http://linux.duke.edu/metadata/repo}repomd':
        raise ValueError(f'invalid repository index: {index}')
    supported = {
        'primary', 'filelists', 'other',
        'primary_db', 'filelists_db', 'other_db',
        'primary_zck', 'filelists_zck', 'other_zck',
        'group', 'group_gz', 'group_zck', 'updateinfo', 'updateinfo_zck',
    }
    seen = set()
    records = []
    for record in root.findall('{*}data'):
        kind = record.get('type')
        if kind not in supported:
            raise ValueError(f'unsupported metadata type {kind!r}; refusing to discard it')
        if kind in seen:
            raise ValueError(f'duplicate metadata type: {kind}')
        seen.add(kind)
        location = record.find('{*}location')
        href = location.get('href', '') if location is not None else ''
        if not re.fullmatch(r'repodata/[A-Za-z0-9][A-Za-z0-9_.+-]*', href):
            raise ValueError(f'unsupported metadata location: {href!r}')
        if href in {'repodata/repomd.xml', 'repodata/repomd.xml.asc'}:
            raise ValueError(f'metadata cannot overwrite the index or signature: {href}')
        checksum = record.find('{*}checksum')
        algorithm = checksum.get('type') if checksum is not None else None
        if algorithm not in {'sha256', 'sha512'}:
            raise ValueError(f'unsupported metadata checksum: {algorithm!r}')
        # The merge regenerates package XML and omits derived caches.
        if not kind.endswith(('_db', '_zck')):
            records.append((kind, href, algorithm, checksum.text or ''))
    if not {'primary', 'filelists', 'other'} <= seen:
        raise ValueError(f'missing primary, filelists or other metadata: {index}')
    if 'group_zck' in seen and not {'group', 'group_gz'} & seen:
        raise ValueError('group metadata requires a non-zchunk copy')
    if 'updateinfo_zck' in seen and 'updateinfo' not in seen:
        raise ValueError('updateinfo metadata requires a non-zchunk copy')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--additional', action='store_true', help='list policy metadata with its type')
    parser.add_argument('index', type=Path)
    args = parser.parse_args()
    records = metadata_files(args.index)
    for kind, href, algorithm, expected in records:
        if args.verify:
            with (args.index.parent.parent / href).open('rb') as stream:
                actual = hashlib.file_digest(stream, algorithm).hexdigest()
            if actual != expected.strip():
                raise ValueError(f'incorrect metadata checksum: {href}')
        elif args.additional:
            if kind in {'group', 'group_gz', 'updateinfo'}:
                print(f'{kind}\t{href}')
        else:
            print(href)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ET.ParseError) as error:
        sys.exit(str(error))
