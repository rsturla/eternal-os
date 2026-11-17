#!/usr/bin/env python3
"""Remove old outputs of replaced source packages from repository metadata."""

import argparse
import gzip
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def source_name(filename):
    if not filename.endswith('.src.rpm'):
        raise ValueError(f'invalid source RPM name: {filename}')
    return filename[:-8].rsplit('-', 2)[0]


def replacements(packages):
    names = set()
    for rpm in packages.rglob('*.rpm'):
        if rpm.name.endswith('.src.rpm'):
            names.add(source_name(rpm.name))
        else:
            source = subprocess.check_output(
                ['rpm', '-qp', '--qf', '%{SOURCERPM}', str(rpm)], text=True
            ).strip()
            if source != '(none)':
                names.add(source_name(source))
    return names


def filter_repository(previous, output, names):
    shutil.copytree(previous, output)
    # The caller verifies the original signature before this transformation.
    (output / 'repodata/repomd.xml.asc').unlink(missing_ok=True)
    index = ET.parse(previous / 'repodata/repomd.xml')
    removed = set()
    for kind in ('primary', 'filelists', 'other'):
        href = index.find(f"{{*}}data[@type='{kind}']/{{*}}location").get('href')
        path = previous / href
        data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
        root = ET.fromstring(data)
        for package in list(root):
            if kind == 'primary':
                source = package.findtext('{*}format/{*}sourcerpm')
                replace = (
                    package.findtext('{*}name') in names
                    if package.find('{*}location').get('href', '').endswith('.src.rpm')
                    else bool(source and source_name(source) in names)
                )
                if replace:
                    removed.add(package.findtext('{*}checksum'))
            else:
                replace = package.get('pkgid') in removed
            if replace:
                root.remove(package)
        root.set('packages', str(len(root)))
        # createrepo_c requires the document namespace without a prefix.
        ET.register_namespace('', root.tag.split('}')[0].removeprefix('{'))
        ET.register_namespace('rpm', 'http://linux.duke.edu/metadata/rpm')
        xml = output / f'{kind}.xml'
        ET.ElementTree(root).write(xml, encoding='utf-8', xml_declaration=True)
        subprocess.run([
            'modifyrepo_c', '--mdtype', kind, '--new-name', f'{kind}.xml.gz',
            '--compress', '--compress-type=gz', '--unique-md-filenames',
            str(xml), str(output / 'repodata'),
        ], check=True)
        xml.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('previous', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    filter_repository(args.previous, args.output, replacements(args.packages))


if __name__ == '__main__':
    main()
