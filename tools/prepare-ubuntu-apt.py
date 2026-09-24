#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve and optionally download ARM64 packages against an immutable Desktop root.

Uses native host APT with isolated configuration, status, caches and logs.
Does not install packages, run maintainer scripts, alter the rootfs or access a tablet.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

import apt_pkg
from debian.deb822 import Deb822


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rootfs', required=True, type=Path, help='Pristine Desktop SquashFS')
    parser.add_argument('--snapshot', required=True, help='Ubuntu snapshot UTC timestamp, YYYYMMDDTHHMMSSZ')
    parser.add_argument('--output', required=True, type=Path, help='New isolated APT directory')
    parser.add_argument('--download', action='store_true', help='Download only; never invoke dpkg installation')
    parser.add_argument('packages', nargs='+', help='Package names or name=version selections')
    args = parser.parse_args()
    try:
        datetime.datetime.strptime(args.snapshot, '%Y%m%dT%H%M%SZ')
    except ValueError:
        parser.error('Snapshot must be a UTC timestamp')
    if not all(re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?:=[A-Za-z0-9.+:~_-]+)?', p) for p in args.packages):
        parser.error('Use package names or exact name=version selections, not APT command options')
    rootfs = args.rootfs.resolve()
    repo = Path(__file__).resolve().parent.parent
    profile = repo / 'ubuntu/26.04.sources'

    def read_root(name):
        return subprocess.check_output(['unsquashfs', '-cat', str(rootfs), name])

    release = dict(word.split('=', 1) for word in shlex.split(read_root('etc/os-release').decode(), comments=True))
    if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '26.04':
        parser.error('This profile supports Ubuntu 26.04 only')
    status = read_root('var/lib/dpkg/status')
    installed = list(Deb822.iter_paragraphs(status.decode()))
    architectures = {p['Architecture'] for p in installed if p.get('Status') == 'install ok installed'}
    if architectures - {'arm64', 'all'} or 'arm64' not in architectures:
        parser.error('Rootfs dpkg status is not an ARM64 installation')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    for name in ['etc/apt/sources.list.d', 'etc/apt/apt.conf.d', 'etc/apt/trusted.gpg.d',
                 'state/lists/partial', 'cache/archives/partial', 'log']:
        (out / name).mkdir(parents=True, exist_ok=True)
    (out / 'state/status').write_bytes(status)
    key = out / 'etc/apt/ubuntu-archive-keyring.gpg'
    key.write_bytes(read_root('usr/share/keyrings/ubuntu-archive-keyring.gpg'))
    sources = list(Deb822.iter_paragraphs(profile.read_text()))
    for source in sources:
        source['Signed-By'] = str(key)
        source['URIs'] = f'https://snapshot.ubuntu.com/ubuntu/{args.snapshot}/'
    (out / 'etc/apt/sources.list.d/ubuntu.sources').write_text('\n'.join(p.dump() for p in sources))

    config = apt_pkg.Configuration()
    for name, value in {
        'Dir::Etc': str(out / 'etc/apt'), 'Dir::Etc::main': '/dev/null',
        'Dir::Etc::parts': str(out / 'etc/apt/apt.conf.d'),
        'Dir::Etc::sourcelist': '/dev/null', 'Dir::Etc::trusted': '/dev/null',
        'Dir::State': str(out / 'state'), 'Dir::State::status': str(out / 'state/status'),
        'Dir::Cache': str(out / 'cache'), 'Dir::Log': str(out / 'log'),
        'APT::Architecture': 'arm64', 'APT::Architectures::': 'arm64',
        'Acquire::Languages': 'none', 'Acquire::http::Timeout': '30',
        'Acquire::https::Timeout': '30', 'APT::Update::Error-Mode': 'any',
        'Acquire::IndexTargets::deb::DEP-11::DefaultEnabled': 'false',
    }.items():
        config.set(name, value)
    conf = out / 'apt.conf'
    conf.write_text(config.dump())
    env = dict(os.environ, APT_CONFIG=str(conf))
    result = {'state': 'PREPARING', 'scope': 'APT resolution/download only, not package installation or boot',
              'snapshot': args.snapshot, 'rootfs_sha256': sha(rootfs), 'rootfs_bytes': rootfs.stat().st_size,
              'dpkg_status_sha256': hashlib.sha256(status).hexdigest(), 'keyring_sha256': sha(key),
              'profile_sha256': sha(profile), 'tool_sha256': sha(Path(__file__)),
              'apt_version': subprocess.check_output(['apt-get', '--version'], text=True).splitlines()[0],
              'requested': args.packages, 'commands': [], 'debs': []}

    def save():
        (out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')

    def apt(stage, words):
        command = ['apt-get', *words]
        print(stage, shlex.join(command), flush=True)
        with (out / (stage + '.log')).open('wb') as log:
            proc = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
        result['commands'].append({'stage': stage, 'argv': command, 'returncode': proc.returncode,
                                   'log_sha256': sha(out / (stage + '.log'))})
        save()
        if proc.returncode:
            raise RuntimeError(f'APT {stage} failed; inspect {out / (stage + ".log")}')

    save()
    try:
        apt('update', ['update'])
        apt('plan', ['--simulate', '--no-remove', 'install', *args.packages])
        apt('uris', ['--print-uris', '--download-only', '--assume-yes', '--no-remove', 'install', *args.packages])
        result['index_sha256'] = {p.name: sha(p) for p in sorted((out / 'state/lists').iterdir())
                                  if p.is_file() and p.name != 'lock'}
        if args.download:
            apt('download', ['--download-only', '--assume-yes', '--no-remove', 'install', *args.packages])
            for path in sorted((out / 'cache/archives').glob('*.deb')):
                fields = Deb822(subprocess.check_output(['dpkg-deb', '--field', str(path)], text=True))
                if fields['Architecture'] not in ('all', 'arm64'):
                    raise RuntimeError(f'Unexpected downloaded architecture: {path.name}')
                result['debs'].append({'file': str(path.relative_to(out)), 'package': fields['Package'],
                                       'version': fields['Version'], 'architecture': fields['Architecture'],
                                       'bytes': path.stat().st_size, 'sha256': sha(path)})
        result['state'] = 'DOWNLOADED_NOT_INSTALLED' if args.download else 'RESOLVED_NOT_INSTALLED'
    except Exception as exc:
        result['state'] = 'FAILED'
        result['error'] = str(exc)
        save()
        raise
    save()
    print(json.dumps({'state': result['state'], 'debs': len(result['debs']), 'output': str(out)}, indent=2))


if __name__ == '__main__':
    main()
