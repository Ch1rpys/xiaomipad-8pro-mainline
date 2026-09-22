#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Merge the two official Desktop layer TARs without host root privileges.

Adapted from erhai overlay-merge-squashfs.py; see NOTICE. Input TARs must be
made by sqfs2tar --root-becomes . --no-skip so inode metadata is preserved.
This handles inode whiteouts and opaque directories, not redirect/metacopy.
No files from the archives are extracted onto the host filesystem.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


def normalized(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError(f'Non-relative archive path: {name}')
    return str(path)


def overlay_attributes(member):
    opaque = False
    for key, value in member.pax_headers.items():
        if key.startswith(('SCHILY.xattr.trusted.overlay.', 'SCHILY.xattr.user.overlay.')):
            attribute = key.rsplit('.', 1)[-1]
            if attribute in ('origin', 'impure', 'uuid'):
                continue  # Copy-up bookkeeping is not part of a flattened rootfs.
            if attribute != 'opaque' or value not in ('y', 'x', 'n'):
                raise ValueError(f'Unsupported overlay attribute on {member.name}: {key}')
            opaque = value == 'y'
        elif key.startswith('LIBARCHIVE.xattr.'):
            raise ValueError('Use sqfs2tar SCHILY xattrs, not an unreviewed archive encoding')
    return opaque


def resolve(items, name):
    seen = set()
    member = items[name]
    while member.islnk():
        if name in seen:
            raise ValueError('Hardlink cycle')
        seen.add(name)
        name = normalized(member.linkname)
        member = items[name]
    return name, member


def merge(base, upper, destination):
    layers = (base, upper)
    entries = []
    selected = {}
    whiteouts, opaque_dirs = [], []
    for index, layer in enumerate(layers):
        items = {normalized(m.name): m for m in layer.getmembers()}
        if len(items) != len(layer.getmembers()):
            raise ValueError('Duplicate paths inside an input layer')
        if '.' not in items or not items['.'].isdir():
            raise ValueError('Layer has no explicit root metadata')
        entries.append(items)
        effective = {p: resolve(items, p)[1] for p in items}
        removed = {p for p, m in effective.items() if m.ischr() and m.devmajor == m.devminor == 0}
        opaque = {p for p, m in effective.items() if overlay_attributes(m)}
        if any(not items[p].isdir() for p in opaque):
            raise ValueError('Opaque marker must belong to a directory')
        barriers = removed | opaque | {p for p, m in items.items() if not m.isdir()}
        selected = {p: item for p, item in selected.items() if p not in removed
                    and not any(str(a) in barriers for a in PurePosixPath(p).parents)}
        selected.update({p: (index, m) for p, m in items.items() if p not in removed})
        whiteouts.extend(sorted(removed))
        opaque_dirs.extend(sorted(opaque))

    canonical = {}
    stats = {'paths': len(selected), 'whiteouts_applied': whiteouts,
             'opaque_directories': opaque_dirs, 'hardlinks': 0, 'xattr_inodes': 0}
    for name, (index, member) in sorted(selected.items()):
        for parent in PurePosixPath(name).parents:
            if str(parent) not in selected or not selected[str(parent)][1].isdir():
                raise ValueError(f'Missing directory ancestor of {name}')
        source_name, target = resolve(entries[index], normalized(member.name))
        key = index, source_name
        header = copy.copy(target)
        header.name = name
        header.pax_headers = {k: v for k, v in target.pax_headers.items()
                              if k not in ('path', 'linkpath', 'size')
                              and not k.startswith(('SCHILY.xattr.trusted.overlay.',
                                                    'SCHILY.xattr.user.overlay.'))}
        if any(k.startswith('SCHILY.xattr.') for k in header.pax_headers):
            stats['xattr_inodes'] += 1
        if key in canonical and not header.isdir():
            header.type, header.linkname, header.size = tarfile.LNKTYPE, canonical[key], 0
            stats['hardlinks'] += 1
            destination.addfile(header)
        else:
            canonical[key] = name
            data = layers[index].extractfile(target) if target.isreg() else None
            try:
                destination.addfile(header, data)
            finally:
                if data:
                    data.close()
    return stats


def sha(path):
    with path.open('rb') as src:
        return hashlib.file_digest(src, 'sha256').hexdigest()


def build_squashfs(archive, image, executable='sqfstar'):
    with tarfile.open(archive, 'r:') as tar:
        root = tar.next()
        if not root or normalized(root.name) != '.' or not root.isdir():
            raise ValueError('Merged TAR must start with its root metadata')
        if any('xattr' in key for key in root.pax_headers):
            raise ValueError('sqfstar root xattrs require an explicit implementation')
    # sqfstar ignores the TAR root entry and otherwise uses host UID/GID/mode.
    with archive.open('rb') as src, image.with_suffix('.log').open('wb') as log:
        subprocess.run([executable, '-comp', 'zstd', '-processors', '4', '-no-progress',
                        '-mkfs-time', '0', '-root-uid', str(root.uid), '-root-gid', str(root.gid),
                        '-root-mode', format(root.mode, 'o'), '-root-time', str(int(root.mtime)),
                        str(image) + '.partial'], stdin=src, stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    Path(str(image) + '.partial').replace(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--desktop', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sqfstar', default='sqfstar')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    archive = out / 'ubuntu-desktop.tar'
    partial = archive.with_suffix('.tar.partial')
    with tarfile.open(args.base, 'r:') as base, tarfile.open(args.desktop, 'r:') as upper, \
            tarfile.open(partial, 'w', format=tarfile.PAX_FORMAT) as result:
        stats = merge(base, upper, result)
    partial.replace(archive)
    print(json.dumps(stats, indent=2), flush=True)
    image = out / 'ubuntu-desktop.squashfs'
    build_squashfs(archive, image, args.sqfstar)
    manifest = {'state': 'ASSEMBLED_NOT_BOOT_TESTED', 'scope': 'Pristine official Desktop merge only; no device setup or account',
                'input_sha256': {'base_tar': sha(args.base), 'desktop_tar': sha(args.desktop)},
                'output_sha256': {p.name: sha(p) for p in (archive, image)}, 'merge': stats}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Desktop archive and SquashFS built; not an installed piano system', flush=True)


if __name__ == '__main__':
    main()
