#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assemble the existing device userspace and Mesa into local Debian packages.

The firmware package, piano-local-firmware, is built by build-firmware-deb.py.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

PROJECT = '2026 The piano mainline project contributors (adapted sources: NOTICE in this directory)'
# Licences whose full text Debian ships in /usr/share/common-licenses; the others are included.
COMMON_LICENSES = {'GPL-2.0-only': 'GPL-2', 'GPL-2.0-or-later': 'GPL-2', 'Apache-2.0': 'Apache-2.0'}


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def spdx(path):
    """SPDX expression of a repository file; files without one are MIT (LICENSE)."""
    m = re.search(rb'SPDX-License-Identifier:\s*(.+?)\s*(?:\*/|-->)?\s*$', path.read_bytes()[:4096], re.M)
    return m.group(1).decode() if m else 'MIT'


def copyright_file(repo, paragraphs):
    """machine-readable debian/copyright: Files paragraphs, then one text per licence used."""
    def text(body):
        return ''.join(f' {line}\n' if line.strip() else ' .\n' for line in body.strip('\n').splitlines())
    mit = (repo / 'LICENSE').read_text().split('Permission is hereby granted', 1)[1].split('\n\nFiles carrying', 1)[0]
    bsd = (repo / 'LICENSES/alsa-ucm-conf-BSD-3-Clause.txt').read_text().split('All rights reserved.', 1)[1]
    full = {'MIT': 'Permission is hereby granted' + mit, 'BSD-3-Clause': bsd}
    out = 'Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n'
    used = []
    for files, holders, licence, comment in paragraphs:
        out += f'\nFiles: {" ".join(sorted(files))}\nCopyright: {holders}\nLicense: {licence}\n'
        if comment:
            out += 'Comment:\n' + text(comment)
        used += [i for i in re.split(r'\s+(?:AND|OR)\s+|[()]', licence) if i and i not in used]
    for licence in used:
        if licence in COMMON_LICENSES:
            body = f'On Debian systems the full text is in /usr/share/common-licenses/{COMMON_LICENSES[licence]}.'
            if licence.endswith('-or-later'):
                body = ('This program is free software; you can redistribute it and/or modify it under\n'
                        'the terms of the GNU General Public License as published by the Free Software\n'
                        'Foundation; either version 2 of the License, or (at your option) any later version.\n\n'
                        + body)
        elif licence in full:
            body = full[licence]
        else:
            raise ValueError(f'No licence text for {licence}')
        out += f'\nLicense: {licence}\n' + text(body)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'thp-live', 'mesa-build', 'busybox', 'avbtool'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--version', required=True)
    ap.add_argument('--support-only', action='store_true', help='Rebuild only the small device integration package')
    a = ap.parse_args()
    repo = Path(__file__).resolve().parents[1]
    a.output.mkdir(parents=True, exist_ok=False)
    stages = a.output / 'stages'
    stages.mkdir()
    receipts = {}
    licences = {}  # stage root -> {installed path: SPDX expression} of files taken from this repository

    def copy(src, root, dest, mode=None):
        target = root / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        target.chmod(mode if mode is not None else 0o644)
        if Path(src).resolve().is_relative_to(repo) and not Path(src).resolve().is_relative_to(repo / 'tools/local'):
            licences.setdefault(root, {})[dest] = spdx(Path(src))

    # Bytecode the tests leave next to the packaged scripts (git-ignored) is not part of a package.
    untracked = shutil.ignore_patterns('__pycache__')

    def tree(src, root, dest):
        for p in sorted(src.rglob('*')):
            if p.is_file() and not p.is_symlink() and '__pycache__' not in p.relative_to(src).parts:
                licences.setdefault(root, {})[str(Path(dest) / p.relative_to(src))] = spdx(p)

    def package(name, root, depends, description, postinst=None, recommends=None, third_party=()):
        """third_party: (files, copyright, licence, comment) paragraphs for files not from this repository;
        every other regular file is attributed to this repository under its SPDX header or MIT."""
        docs = root / 'usr/share/doc' / name
        docs.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / 'NOTICE', docs / 'NOTICE')
        claimed = {f for paragraph in third_party for f in paragraph[0]}
        own = {}
        for p in root.rglob('*'):
            rel = str(p.relative_to(root))
            if p.is_file() and not p.is_symlink() and not any(rel == c or rel.startswith(c.rstrip('*'))
                                                              for c in claimed) and rel != f'usr/share/doc/{name}/NOTICE':
                own.setdefault(licences.get(root, {}).get(rel, 'MIT'), []).append(rel)
        paragraphs = [(files, PROJECT, licence, None) for licence, files in sorted(own.items())]
        paragraphs += [((f'usr/share/doc/{name}/NOTICE',), PROJECT, 'MIT', None), *third_party]
        (docs / 'copyright').write_text(copyright_file(repo, paragraphs))
        control = root / 'DEBIAN'
        control.mkdir()
        (control / 'control').write_text(
            f'Package: {name}\nVersion: {a.version}\nArchitecture: arm64\n'
            'Maintainer: Piano local build <piano@localhost>\n'
            f'Depends: {depends}\n' + (f'Recommends: {recommends}\n' if recommends else '') +
            f'Description: {description}\n')
        if postinst:
            (control / 'postinst').write_text(postinst)
            (control / 'postinst').chmod(0o755)
        owned = {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
                 if p.is_file() and not p.is_symlink() and not p.is_relative_to(control)}
        deb = a.output / f'{name}_{a.version}_arm64.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z1', '--build', str(root), str(deb)], check=True)
        receipts[name] = {'file': deb.name, 'sha256': sha(deb), 'files': owned}

    support = stages / 'piano-device-support'
    shutil.copytree(repo / 'packaging/piano-device-support', support, ignore=untracked)
    tree(repo / 'packaging/piano-device-support', support, '.')
    for p in support.rglob('*'):
        if p.is_file() and p.read_bytes().startswith(b'#!'):
            p.chmod(0o755)
    copy(repo / 'device/boot/piano-boot-switch', support, 'usr/sbin/piano-boot-switch', 0o755)
    copy(repo / 'device/boot/piano-slot-success', support, 'usr/sbin/piano-slot-success', 0o755)
    copy(repo / 'device/boot/piano_bootslot.py', support, 'usr/lib/piano/boot/piano_bootslot.py', 0o644)
    copy(a.thp_live, support, 'usr/libexec/piano/piano-thp-live', 0o755)
    copy(a.busybox, support, 'usr/libexec/piano/busybox', 0o755)
    copy(repo / 'device/platform/piano-physical-platform', support, 'usr/libexec/piano/piano-physical-platform', 0o755)
    copy(repo / 'initramfs/usb-diag', support, 'usr/libexec/piano/usb-diag', 0o755)
    network = json.loads((repo / 'initramfs/network.json').read_text())
    (support / 'etc/piano-network').write_text(''.join(f'PIANO_{k.upper()}={v}\n' for k, v in network.items()))
    # build-persistent-boot.py imports initramfs_archive from its own directory.
    for source, name in [(repo / 'tools/build-persistent-boot.py', 'build-persistent-boot.py'),
                         (repo / 'tools/initramfs_archive.py', 'initramfs_archive.py'),
                         (repo / 'tools/local/aosp-mkbootimg/mkbootimg.py', 'mkbootimg.py'),
                         (a.avbtool, 'avbtool.py')]:
        copy(source, support, 'usr/lib/piano/boot/' + name, 0o755)
    shutil.copytree(repo / 'tools/local/aosp-mkbootimg/gki', support / 'usr/lib/piano/boot/gki',
                    ignore=shutil.ignore_patterns('__pycache__', '*test*'))
    # piano-boot-update runs the packaged copy: it must import from the package alone.
    subprocess.run(['python3', '-E', '-s', '-B', str((support / 'usr/lib/piano/boot/build-persistent-boot.py').resolve()), '--help'],
                   check=True, stdout=subprocess.DEVNULL, cwd='/')
    busybox = re.search(r'^package=busybox-static_(\S+)_arm64\.deb$',
                        (repo / 'tools/fetch-busybox-arm64.sh').read_text(), re.M).group(1)
    support_third_party = [
        (('usr/lib/piano/boot/mkbootimg.py', 'usr/lib/piano/boot/gki/*'), 'The Android Open Source Project',
         'Apache-2.0', 'AOSP platform/system/tools/mkbootimg, the checkout pinned by tools/fetch-aosp-mkbootimg.sh;\n'
         'unmodified, tests excluded.'),
        (('usr/lib/piano/boot/avbtool.py',), 'The Android Open Source Project', 'MIT',
         'AOSP platform/external/avb avbtool.py, unmodified; its MIT notice is in the file header.'),
        (('usr/libexec/piano/busybox',),
         'Erik Andersen, Rob Landley, Denys Vlasenko and other BusyBox contributors', 'GPL-2.0-only',
         f'The busybox-static {busybox} arm64 binary from Ubuntu, unmodified (pinned by\n'
         'tools/fetch-busybox-arm64.sh). Its corresponding source is the Ubuntu source package\n'
         f'busybox {busybox}: https://launchpad.net/ubuntu/+source/busybox/{busybox}'),
        (('usr/libexec/piano/piano-thp-live',), 'ianchb; Niels Lohmann; ' + PROJECT,
         'Apache-2.0 AND MIT', 'Built from device/piano-thp: files adapted from ianchb/xiaomi-sheng-thp are\n'
         'Apache-2.0, the rest MIT (see NOTICE); it includes the MIT nlohmann JSON headers.'),
    ]
    package('piano-device-support', support,
            'python3, openssl, device-tree-compiler, dracut, kmod, init-system-helpers',
            'Piano platform, touchscreen and persistent boot integration',
            '#!/bin/sh\nset -e\nif [ "$1" = configure ]; then\n'
            # piano-thp.service is udev-activated only; remove the multi-user.target link
            # and deb-systemd-helper state left by versions that enabled it.
            ' deb-systemd-helper purge piano-thp.service >/dev/null\n'
            ' deb-systemd-helper enable piano-slot-success.service piano-debug.service '
            'piano-debug-timeout.service >/dev/null\nfi\n',
            recommends='openssh-server',  # developer mode only; piano-devmode refuses without sshd
            third_party=support_third_party)
    if a.support_only:
        (a.output / 'manifest.json').write_text(json.dumps(receipts, indent=2) + '\n')
        return

    mesa = stages / 'piano-mesa'
    subprocess.run(['python3', str(repo / 'tools/prepare-mesa-initramfs.py'), '--mesa-build', str(a.mesa_build),
                    '--stage', str(mesa)], stdout=subprocess.DEVNULL, check=True)
    mesa_source = json.loads((repo / 'mesa/source.json').read_text())
    package('piano-mesa', mesa, 'libc6, libdrm2, libexpat1, libzstd1, zlib1g',
            'Isolated Mesa 26.2 with piano A830 input lock',
            third_party=[((mesa_source['prefix'].lstrip('/') + '/*',), 'Mesa contributors (per-file notices)',
                          'MIT', f'Mesa {mesa_source["tag"]} ({mesa_source["url"]}, commit {mesa_source["commit"]})\n'
                          f'with {mesa_source["patch"]} from this repository. Most of Mesa is MIT; some files\n'
                          'carry other permissive licences, listed in docs/license.rst of that source.')])

    desktop = stages / 'piano-ubuntu-desktop'
    shutil.copytree(repo / 'packaging/piano-ubuntu-desktop', desktop, ignore=untracked)
    tree(repo / 'packaging/piano-ubuntu-desktop', desktop, '.')
    # ALSA UCM for the internal-microphone card (device/audio/ucm2, MIT/BSD-3-Clause, see NOTICE);
    # its conf.d entry is a relative symlink, kept as one.
    shutil.copytree(repo / 'device/audio/ucm2', desktop / 'usr/share/alsa/ucm2', symlinks=True)
    tree(repo / 'device/audio/ucm2', desktop, 'usr/share/alsa/ucm2')
    env = desktop / 'etc/environment.d/50-piano-mesa.conf'
    env.parent.mkdir(parents=True)
    prefix = json.loads((repo / 'mesa/source.json').read_text())['prefix']
    env.write_text(f'LD_LIBRARY_PATH={prefix}/lib\nLIBGL_DRIVERS_PATH={prefix}/lib/dri\n')
    dropin = desktop / 'etc/systemd/system/gdm.service.d/50-piano-mesa.conf'
    dropin.parent.mkdir(parents=True)
    dropin.write_text('[Service]\n' + ''.join('Environment=' + l + '\n' for l in env.read_text().splitlines()))
    # The speaker up-mix is a stream property: the same file for PulseAudio and native PipeWire clients.
    upmix = 'usr/share/pipewire/pipewire-pulse.conf.d/50-piano-speaker-upmix.conf'
    copy(repo / 'packaging/piano-ubuntu-desktop' / upmix, desktop,
         'usr/share/pipewire/client.conf.d/50-piano-speaker-upmix.conf')
    # fake-hwclock: the RTC cannot be set (TD-022); it restores the time saved at shutdown or hourly.
    package('piano-ubuntu-desktop', desktop, 'piano-mesa, gdm3, gnome-shell (>= 50), fake-hwclock, python3, console-setup, snapd, init-system-helpers',
            'Piano Ubuntu desktop defaults: graphics, clock without RTC, speaker up-mix and UCM, '
            'GNOME Shell 50 on-screen keyboard guard',
            '#!/bin/sh\nset -e\nif [ "$1" = configure ]; then\n'
            ' deb-systemd-helper enable piano-firefox-snap-remove.service >/dev/null\nfi\n',
            third_party=[(('usr/share/alsa/ucm2/*',),
                          '2026 bluseliu50 and piano mainline contributors; '
                          '2019 Advanced Linux Sound Architecture (ALSA) project', 'MIT AND BSD-3-Clause',
                          'device/audio/ucm2, adapted from blu-sharky/debian-piano and alsa-ucm-conf (see NOTICE).')])
    (a.output / 'manifest.json').write_text(json.dumps(receipts, indent=2) + '\n')
    print('Local packages created; no packages installed or device accessed')


if __name__ == '__main__':
    main()
