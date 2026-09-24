#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Package the piano RAM-only diagnostic using the tested stock v2 container.

Adapted from erhai tools/build-mainline-boot.py; see NOTICE. No flash commands.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

CMDLINE_BASE = ('rdinit=/init console=ttyMSM0,115200n8 ignore_loglevel log_buf_len=2M '
                'panic=15')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', type=Path, required=True)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--initramfs', type=Path, required=True)
    parser.add_argument('--dtb', type=Path, required=True)
    parser.add_argument('--mkbootimg', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--boot-id', default='mainline-r1',
                        help='Short experiment label recorded in the kernel command line')
    parser.add_argument('--diagnostic', choices=('console', 'acm', 'ncm'), default='console',
                        help='Observation channel; all modes retain the 60-second timer')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', args.boot_id):
        parser.error('boot-id must be a 1-64 character ASCII experiment label')
    cmdline = (f'{CMDLINE_BASE} piano.boot={args.boot_id} '
               f'piano.diag={args.diagnostic} piano.diag_timeout=60')
    source, kout = args.kernel_source.resolve(), args.kernel_out.resolve()
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        parser.error('Commit kernel changes before packaging a candidate')
    build = json.loads((kout / 'build-result.json').read_text())
    if head != build['kernel_commit']:
        parser.error('Kernel build does not match the source commit')
    for name, expected in build['files'].items():
        if sha(kout / name) != expected:
            parser.error(f'Build artifact changed: {name}')
    overlay = json.loads((args.dtb.parent / 'manifest.json').read_text())
    if overlay['outputs_sha256'][args.dtb.name] != sha(args.dtb):
        parser.error('Packaging DTB does not match its overlay audit')
    if overlay['inputs_sha256']['mainline_dtb'] != build['files']['arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano.dtb']:
        parser.error('Packaging DTB was built from another kernel DTB')
    config = (kout / '.config').read_text().splitlines()
    for setting in ('CONFIG_PSTORE_CONSOLE=y', 'CONFIG_PSTORE_RAM=y',
                    '# CONFIG_SCSI_UFSHCD is not set', '# CONFIG_MMC is not set',
                    '# CONFIG_MTD is not set', '# CONFIG_BLK_DEV_NVME is not set'):
        if setting not in config:
            parser.error(f'Missing RAM-only diagnostic configuration: {setting}')
    image = kout / 'arch/arm64/boot/Image'
    ram_build_id = subprocess.check_output(
        ['cpio', '--extract', '--to-stdout', '--quiet', 'etc/build-id'],
        input=gzip.decompress(args.initramfs.read_bytes())).decode().strip()
    if not re.fullmatch(r'[0-9a-f]{64}', ram_build_id):
        parser.error('The ramdisk must contain its exact diagnostic build-id')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    boot = out / 'boot-piano-ram.img'
    subprocess.run(['python3', str(args.mkbootimg.resolve()),
                    '--header_version', '2', '--pagesize', '4096', '--base', '0',
                    '--kernel_offset', '0x00008000', '--ramdisk_offset', '0x01000000',
                    '--tags_offset', '0x00000100', '--dtb_offset', '0x01f00000',
                    '--kernel', str(image), '--ramdisk', str(args.initramfs.resolve()),
                    '--dtb', str(args.dtb.resolve()), '--os_version', '16.0.0',
                    '--os_patch_level', '2026-02', '--cmdline', cmdline,
                    '--output', str(boot)], check=True)
    if boot.stat().st_size > 100663296:
        raise RuntimeError('Candidate exceeds the observed piano boot partition size')
    manifest = {
        'status': 'OFFLINE_CANDIDATE_NOT_DEVICE_TESTED', 'kernel_commit': head,
        'cmdline': cmdline, 'boot_sha256': sha(boot), 'boot_size': boot.stat().st_size,
        'diagnostic': args.diagnostic,
        'ram_build_id': ram_build_id,
        'inputs_sha256': {'Image': sha(image), 'dtb': sha(args.dtb),
                          'initramfs': sha(args.initramfs), 'mkbootimg': sha(args.mkbootimg),
                          'config': sha(kout / '.config')},
        'scope': 'fastboot boot only; diagnostic userspace, no persistent storage drivers or native panel support; firmware framebuffer support is candidate-specific',
        'recovery': '60-second PID1 timer and panic=15; early hangs may require the person present to reset',
    }
    if args.diagnostic == 'ncm':
        if 'CONFIG_USB_CONFIGFS_NCM=y' not in config:
            parser.error('NCM diagnostics require the built-in kernel function')
        network = Path(__file__).resolve().parent.parent / 'initramfs/network.json'
        manifest['network'] = json.loads(network.read_text())
        manifest['inputs_sha256']['network'] = sha(network)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
