#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The four data stages of .github/workflows/root-image.yml; no device I/O."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / 'out'
INPUTS = OUT / 'ci-arm64-inputs'
CACHE = OUT / 'ci-arm64-cache'
BUILD = OUT / 'ci-arm64-build'
ARTIFACTS = OUT / 'ci-arm64-artifacts'
E2 = OUT / 'ci-arm64-tools/e2fsprogs'
LOCK = json.loads((REPO / 'ubuntu/root-image.json').read_text())
LAYERS = json.loads((REPO / 'ubuntu/desktop-layers.json').read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check(path, digest):
    if sha(path) != digest:
        raise ValueError(f'SHA-256 mismatch: {path}')


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def fetch(url, path, digest):
    if not path.exists():
        partial = path.with_suffix(path.suffix + '.partial')
        with urllib.request.urlopen(url, timeout=120) as src, partial.open('wb') as dst:
            shutil.copyfileobj(src, dst)
        check(partial, digest)
        partial.rename(path)
    check(path, digest)


def base():
    image = CACHE / 'ubuntu-desktop.squashfs'
    if image.exists():
        check(image, LAYERS['merged_squashfs_sha256'])
        print('Pristine cache SHA-256 verified', flush=True)
        return
    iso = INPUTS / 'ubuntu-26.04-desktop-arm64.iso'
    fetch(LAYERS['url'], iso, LAYERS['iso_sha256'])
    layers = INPUTS / 'layers'
    run('bash', REPO / 'tools/prepare-ubuntu-desktop.sh',
        env=dict(os.environ, UBUNTU_ISO=str(iso), OUT_DIR=str(layers)))
    iso.unlink()
    tars = []
    for layer, key in zip(LAYERS['layer_order'], ('base_tar', 'desktop_tar')):
        source = layers / layer
        check(source, LAYERS['files'][layer])
        tar = INPUTS / (layer + '.tar')
        with tar.open('wb') as dst:
            run('sqfs2tar', '--root-becomes', '.', '--no-skip', source, stdout=dst)
        check(tar, LAYERS['tar_sha256'][key])
        source.unlink()
        tars.append(tar)
    run('python3', REPO / 'tools/merge-desktop-tars.py', '--base', tars[0], '--desktop', tars[1],
        '--output', CACHE)
    check(CACHE / 'ubuntu-desktop.tar', LAYERS['merged_tar_sha256'])
    check(image, LAYERS['merged_squashfs_sha256'])
    for path in [*tars, CACHE / 'ubuntu-desktop.tar']:
        path.unlink()


def inputs():
    for deb in LOCK['release_debs']:
        fetch(deb['url'], INPUTS / deb['file'], deb['sha256'])
    run('python3', REPO / 'tools/build-device-debs.py', '--desktop-only',
        '--version', LOCK['desktop_version'], '--output', INPUTS / 'desktop')
    run('python3', REPO / 'tools/prepare-ubuntu-apt.py', '--rootfs', CACHE / 'ubuntu-desktop.squashfs',
        '--snapshot', LOCK['apt_snapshot'], '--output', INPUTS / 'apt',
        '--mozilla-firefox', '--download', *LOCK['apt_packages'])
    apt = json.loads((INPUTS / 'apt/manifest.json').read_text())
    expected = {d['package']: d for d in LOCK['apt_debs']}
    firefox = json.loads((REPO / 'ubuntu/firefox/source.json').read_text())
    keys = ('package', 'version', 'architecture', 'sha256')
    expected['firefox'] = {k: firefox[k] for k in keys}
    actual = {d['package']: {k: d[k] for k in keys} for d in apt['debs']}
    if actual != expected:
        raise ValueError(f'APT resolution differs from root-image.json: {actual}')


def build():
    # CI images use a new ephemeral AVB key, never the release owner's private key.
    key = INPUTS / 'ci-boot-key.pem'
    old_umask = os.umask(0o077)
    try:
        run('openssl', 'genrsa', '-out', key, '4096')
    finally:
        os.umask(old_umask)
    kernel = next(d for d in LOCK['release_debs'] if d['package'].startswith('linux-image-'))
    command = ['python3', REPO / 'tools/build-rootfs-image.py', '--backend', 'chroot',
               '--squashfs', CACHE / 'ubuntu-desktop.squashfs',
               '--squashfs-sha256', LAYERS['merged_squashfs_sha256'],
               '--sqfs2tar', shutil.which('sqfs2tar'), '--mke2fs', E2 / 'misc/mke2fs',
               '--mke2fs-config', E2 / 'misc/mke2fs.conf', '--e2fsck', E2 / 'e2fsck/e2fsck',
               '--debugfs', E2 / 'debugfs/debugfs', '--dumpe2fs', E2 / 'misc/dumpe2fs',
               '--kernel-deb', INPUTS / kernel['file'], '--apt-manifest', INPUTS / 'apt/manifest.json',
               '--boot-profile', REPO / 'ubuntu/boot-profile.json', '--boot-key', key,
               '--output', BUILD]
    for deb in LOCK['release_debs']:
        if deb != kernel:
            command.extend(['--deb', INPUTS / deb['file']])
    command.extend(['--deb', INPUTS / 'desktop' / f'piano-ubuntu-desktop_{LOCK["desktop_version"]}_arm64.deb'])
    try:
        run(*command)
    finally:
        key.unlink(missing_ok=True)


def artifacts():
    manifest = json.loads((BUILD / 'manifest.json').read_text())
    verification = json.loads((BUILD / 'verification.json').read_text())
    assert manifest['state'] == 'ROOT_IMAGE_BUILT_OFFLINE_CHECKS_PASS_NOT_BOOTED'
    assert manifest['backend'] == 'chroot' and verification['passed']
    assert len(verification['checks']) >= 31
    sparse = manifest['sparse']
    assert sparse['ext4']['dont_care_on_used_bytes'] == 0
    assert sparse['ext4']['fill_on_free_bytes'] == 0
    assert sparse['expanded_bytes'] == 60 << 30
    # Keep the exact initrd for the baseline cpio comparison and cold boot.
    initrd = ARTIFACTS / 'initrd.img'
    release = manifest['kernel_release']
    run(E2 / 'debugfs/debugfs', '-R', f'dump /boot/initrd.img-{release} {initrd}', BUILD / 'root.ext4')
    check(initrd, manifest['boot_files_sha256'][f'/boot/initrd.img-{release}'])
    run(E2 / 'debugfs/debugfs', '-R', f'dump /boot/vmlinuz-{release} {ARTIFACTS / "vmlinuz"}', BUILD / 'root.ext4')
    shutil.copyfile(BUILD / 'guest/dpkg-query.txt', ARTIFACTS / 'dpkg-query.txt')
    # cpio lists only; no extraction or interpretation of archive paths on the host.
    with subprocess.Popen(['zstd', '-qdc', str(initrd)], stdout=subprocess.PIPE) as proc:
        with (ARTIFACTS / 'initrd-members.txt').open('wb') as dst:
            run('cpio', '-it', '--quiet', stdin=proc.stdout, stdout=dst)
        proc.stdout.close()
        assert proc.wait() == 0
    for name in ('manifest.json', 'verification.json', 'guest-profile.jsonl'):
        shutil.copyfile(BUILD / name, ARTIFACTS / name)
    shutil.copytree(BUILD / 'ubuntu-set', ARTIFACTS / 'ubuntu-set')
    shutil.copyfile(REPO / 'ubuntu/desktop-layers.json', ARTIFACTS / 'desktop-layers.json')
    shutil.copyfile(REPO / 'ubuntu/root-image.json', ARTIFACTS / 'root-image-inputs.json')
    (ARTIFACTS / 'source.json').write_text(json.dumps({
        'repository': 'https://github.com/yzddmr6/xiaomipad-8pro-mainline',
        'commit': subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip(),
        'run_url': f'https://github.com/{os.environ.get("GITHUB_REPOSITORY", "")}/actions/runs/{os.environ.get("GITHUB_RUN_ID", "")}',
    }, indent=2) + '\n')
    # Release-style 1900 MiB parts. Delete the local inspection image before splitting.
    (BUILD / 'root.ext4').unlink()
    image = BUILD / 'root.sparse.img'
    check(image, manifest['outputs']['root.sparse.img']['sha256'])
    if image.stat().st_size > 1900 << 20:
        run('split', '-b', '1900M', '-d', '-a', '2', image, ARTIFACTS / 'root.sparse.img.part')
        shutil.copyfile(BUILD / 'SHA256SUMS', ARTIFACTS / 'SHA256SUMS.root')
        image.unlink()
    else:
        image.rename(ARTIFACTS / image.name)
    table = ['| Stage | Native ARM64 seconds | SPEED2 seconds |', '|---|---:|---:|']
    for name, seconds in manifest['timings_seconds'].items():
        old = LOCK['baseline']['timings_seconds'].get('guest' if name == 'chroot' else name, '—')
        table.append(f'| {name} | {seconds} | {old} |')
    table.append(f'| Total builder | {manifest["total_seconds"]} | {LOCK["baseline"]["seconds"]} |')
    summary = '\n'.join(table) + '\n'
    print(summary, flush=True)
    (ARTIFACTS / 'timings.md').write_text(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('base', 'inputs', 'build', 'artifacts'))
    args = parser.parse_args()
    INPUTS.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    usage = []
    def sample():
        while not stop.is_set():
            usage.append(shutil.disk_usage(OUT)._asdict())
            stop.wait(1)
    monitor = threading.Thread(target=sample)
    monitor.start()
    started = time.monotonic()
    try:
        globals()[args.stage]()
    finally:
        stop.set()
        monitor.join()
        report = {'stage': args.stage, 'seconds': round(time.monotonic() - started, 1),
                  'min_free_bytes': min(s['free'] for s in usage),
                  'max_used_bytes': max(s['used'] for s in usage)}
        (ARTIFACTS / f'{args.stage}-stage.json').write_text(json.dumps(report, indent=2) + '\n')
        if args.stage == 'artifacts':
            sums = ARTIFACTS / 'SHA256SUMS'
            sums.write_text(''.join(f'{sha(p)}  {p.relative_to(ARTIFACTS)}\n'
                                   for p in sorted(ARTIFACTS.rglob('*')) if p.is_file() and p != sums))
        print(json.dumps(report), flush=True)
