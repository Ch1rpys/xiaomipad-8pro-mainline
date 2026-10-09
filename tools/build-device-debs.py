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
import shutil
import subprocess


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


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

    def copy(src, root, dest, mode=None):
        target = root / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        target.chmod(mode if mode is not None else 0o644)

    def package(name, root, depends, description, postinst=None, recommends=None):
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
    shutil.copytree(repo / 'packaging/piano-device-support', support)
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
    for source, name in [(repo / 'tools/build-persistent-boot.py', 'build-persistent-boot.py'),
                         (repo / 'tools/local/aosp-mkbootimg/mkbootimg.py', 'mkbootimg.py'),
                         (a.avbtool, 'avbtool.py')]:
        copy(source, support, 'usr/lib/piano/boot/' + name, 0o755)
    shutil.copytree(repo / 'tools/local/aosp-mkbootimg/gki', support / 'usr/lib/piano/boot/gki',
                    ignore=shutil.ignore_patterns('__pycache__', '*test*'))
    package('piano-device-support', support,
            'python3, openssl, device-tree-compiler, dracut, kmod, init-system-helpers',
            'Piano platform, touchscreen and persistent boot integration',
            '#!/bin/sh\nset -e\nif [ "$1" = configure ]; then\n'
            # piano-thp.service is udev-activated only; remove the multi-user.target link
            # and deb-systemd-helper state left by versions that enabled it.
            ' deb-systemd-helper purge piano-thp.service >/dev/null\n'
            ' deb-systemd-helper enable piano-slot-success.service piano-debug.service '
            'piano-debug-timeout.service >/dev/null\nfi\n',
            recommends='openssh-server')  # developer mode only; piano-devmode refuses without sshd
    if a.support_only:
        (a.output / 'manifest.json').write_text(json.dumps(receipts, indent=2) + '\n')
        return

    mesa = stages / 'piano-mesa'
    subprocess.run(['python3', str(repo / 'tools/prepare-mesa-initramfs.py'), '--mesa-build', str(a.mesa_build),
                    '--stage', str(mesa)], stdout=subprocess.DEVNULL, check=True)
    package('piano-mesa', mesa, 'libc6, libdrm2, libexpat1, libzstd1, zlib1g',
            'Isolated Mesa 26.2 with piano A830 input lock')

    desktop = stages / 'piano-ubuntu-desktop'
    env = desktop / 'etc/environment.d/50-piano-mesa.conf'
    env.parent.mkdir(parents=True)
    prefix = json.loads((repo / 'mesa/source.json').read_text())['prefix']
    env.write_text(f'LD_LIBRARY_PATH={prefix}/lib\nLIBGL_DRIVERS_PATH={prefix}/lib/dri\n')
    dropin = desktop / 'etc/systemd/system/gdm.service.d/50-piano-mesa.conf'
    dropin.parent.mkdir(parents=True)
    dropin.write_text('[Service]\n' + ''.join('Environment=' + l + '\n' for l in env.read_text().splitlines()))
    monitors = '''<monitors version="2"><configuration><logicalmonitor><x>0</x><y>0</y><scale>2</scale><primary>yes</primary><monitor><monitorspec><connector>None-1</connector><vendor>unknown</vendor><product>unknown</product><serial>unknown</serial></monitorspec><mode><width>3200</width><height>2136</height><rate>60</rate></mode></monitor></logicalmonitor></configuration></monitors>\n'''
    for rel in ('etc/skel/.config/monitors.xml', 'var/lib/gdm3/.config/monitors.xml',
                'var/lib/gnome-initial-setup/.config/monitors.xml'):
        f = desktop / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(monitors)
    package('piano-ubuntu-desktop', desktop, 'piano-mesa, gdm3', 'Piano Ubuntu desktop graphics defaults')
    (a.output / 'manifest.json').write_text(json.dumps(receipts, indent=2) + '\n')
    print('Local packages created; no packages installed or device accessed')


if __name__ == '__main__':
    main()
