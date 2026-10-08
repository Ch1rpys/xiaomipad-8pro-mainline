#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build piano's v4 boot triplet and a v2 RAM check from explicit inputs.

Adapted from erhai build-mainline-gki.py/sign-boot-triplet.py; see NOTICE.
This tool writes regular output files only. It never discovers or flashes disks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import uuid
import zlib


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def empty_ramdisk():
    """gzip of an empty newc archive, byte-identical on every Python version.

    gzip.compress() wrote OS byte 0x03 under Python 3.12 and 0xff under 3.14,
    so init_boot.img depended on the interpreter. The header is written here
    with mtime 0, XFL 2 (level 9) and OS 3, the bytes of the 3.12-built release
    set; the body is zlib's raw deflate at level 9.
    """
    name = b'TRAILER!!!\0'
    blob = b'070701' + b''.join(f'{n:08x}'.encode() for n in
                              (0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0)) + name
    blob += b'\0' * (-len(blob) % 4)
    deflate = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    body = deflate.compress(blob) + deflate.flush()
    return (b'\x1f\x8b\x08\x00' + struct.pack('<I', 0) + b'\x02\x03' + body +
            struct.pack('<II', zlib.crc32(blob) & 0xffffffff, len(blob)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('kernel', 'dtb', 'initrd', 'profile', 'mkbootimg', 'avbtool', 'key', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--root-partuuid', type=uuid.UUID, required=True)
    p.add_argument('--bt-address-file', type=Path)
    p.add_argument('--debug', action='store_true')
    p.add_argument('--debug-timeout', type=int, default=0)
    p.add_argument('--module-blacklist', help='Explicit comma-separated module control for a debug boot')
    a = p.parse_args()
    if a.debug_timeout and (not a.debug or not 60 <= a.debug_timeout <= 900):
        p.error('A 60–900 second timeout is only available for explicit debug boots')
    if a.module_blacklist and (not a.debug or not re.fullmatch(r'[a-z0-9_]+(?:,[a-z0-9_]+)*', a.module_blacklist)):
        p.error('Module controls require an explicit debug boot and valid module names')
    profile = json.loads(a.profile.read_text())
    for name in ('boot', 'init_boot', 'vendor_boot'):
        if profile[name]['header_version'] != 4 or profile[name]['capacity'] <= 0:
            p.error('Expected verified stock v4 geometry')
    a.output.mkdir(parents=True, exist_ok=False)
    out = a.output.resolve()
    shutil.copyfile(a.profile, out / 'profile.json')
    dtb = out / 'piano-boot.dtb'
    shutil.copyfile(a.dtb, dtb)
    if a.bt_address_file:
        address = a.bt_address_file.read_text().strip()
        if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
            p.error('Invalid local Bluetooth address')
        raw = bytes.fromhex(address.replace(':', ''))
        if raw in (bytes(6), b'\xff' * 6):
            p.error('Bluetooth address is not usable')
        node = '/soc@0/geniqup@8c0000/serial@898000/bluetooth'
        compatible = subprocess.check_output(['fdtget', '-t', 's', str(dtb), node, 'compatible'], text=True).strip()
        if compatible != 'qcom,wcn7860-bt':
            p.error('Expected the piano WCN7860 node')
        # hci_dev_get_bd_addr_from_property() consumes a little-endian bdaddr_t.
        subprocess.run(['fdtput', '-t', 'bx', str(dtb), node, 'local-bd-address',
                        *[f'{b:02x}' for b in reversed(raw)]], check=True)
    cmdline = (f'root=PARTUUID={a.root_partuuid} rootfstype=ext4 rw rootwait '
               'console=ttyMSM0,115200n8 log_buf_len=2M panic=15 '
               'msm.separate_gpu_kms=1 piano.boot=persistent systemd.gpt_auto=0 bootconfig')
    # V4 may expose the firmware serial only in bootconfig. Keep the explicit
    # development gadget bound to the locally verified installation profile.
    serial = profile.get('serial')
    if not isinstance(serial, str) or not re.fullmatch('[A-Za-z0-9]+', serial):
        p.error('Profile requires the verified device serial')
    cmdline += ' androidboot.serialno=' + serial
    if a.debug:
        cmdline += ' piano.debug=1'
    if a.debug_timeout:
        cmdline += f' piano.debug_timeout={a.debug_timeout}'
    if a.module_blacklist:
        cmdline += ' module_blacklist=' + a.module_blacklist
    empty = out / 'empty.cpio.gz'
    empty.write_bytes(empty_ramdisk())
    mk = ['python3', str(a.mkbootimg)]
    common = ['--header_version', '4', '--pagesize', str(profile['vendor_boot']['page_size'])]
    os_version = profile['boot']['avb_properties']['com.android.build.boot.os_version']
    patch = profile['boot']['avb_properties']['com.android.build.boot.security_patch']
    boot_version = ['--os_version', os_version + '.0.0', '--os_patch_level', patch[:7]]
    subprocess.run(mk + common + boot_version + ['--kernel', str(a.kernel), '--cmdline', cmdline,
                                  '--output', str(out / 'boot.img')], check=True)
    subprocess.run(mk + common + boot_version + ['--ramdisk', str(empty), '--output', str(out / 'init_boot.img')], check=True)
    vendor = profile['vendor_boot']
    offsets = ['--base', '0', '--kernel_offset', str(vendor['kernel_addr']),
               '--ramdisk_offset', str(vendor['ramdisk_addr']), '--tags_offset', str(vendor['tags_addr']),
               '--dtb_offset', str(vendor['dtb_addr'])]
    subprocess.run(mk + common + offsets + ['--vendor_ramdisk', str(a.initrd), '--dtb', str(dtb),
                                           '--vendor_boot', str(out / 'vendor_boot.img')], check=True)
    outputs = {}
    for name in ('boot', 'init_boot', 'vendor_boot'):
        image = out / (name + '.img')
        raw_hash = sha(image)
        salt = hashlib.sha256(b'piano-avb\0' + name.encode() + bytes.fromhex(raw_hash)).hexdigest()
        command = ['python3', str(a.avbtool), 'add_hash_footer', '--image', str(image),
                   '--partition_name', name, '--partition_size', str(profile[name]['capacity']),
                   '--rollback_index', str(profile[name]['rollback_index']), '--salt', salt,
                   '--algorithm', 'SHA256_RSA4096', '--key', str(a.key)]
        for prop, value in profile[name].get('avb_properties', {}).items():
            command += ['--prop', prop + ':' + value]
        subprocess.run(command, check=True)
        subprocess.run(['python3', str(a.avbtool), 'verify_image', '--image', str(image),
                        '--key', str(a.key)], check=True)
        if image.stat().st_size != profile[name]['capacity']:
            raise ValueError('Signed image must occupy the complete partition')
        outputs[name] = {'file': image.name, 'bytes': image.stat().st_size, 'sha256': sha(image)}
    ram = out / 'boot-ram-check.img'
    subprocess.run(mk + ['--header_version', '2', '--pagesize', str(vendor['page_size'])] + offsets +
                   ['--kernel', str(a.kernel), '--ramdisk', str(a.initrd), '--dtb', str(dtb),
                    '--cmdline', cmdline, '--output', str(ram)], check=True)
    manifest = {'kind': 'piano-persistent-v4', 'cmdline': cmdline, 'root_partuuid': str(a.root_partuuid),
                'debug': a.debug, 'debug_timeout': a.debug_timeout,
                'inputs': {n: sha(getattr(a, n)) for n in ('kernel', 'dtb', 'initrd', 'profile', 'mkbootimg', 'avbtool')},
                'private_bt_address_injected': bool(a.bt_address_file), 'effective_dtb_sha256': sha(dtb),
                'outputs': outputs, 'ram_image': {'file': ram.name, 'sha256': sha(ram)},
                'scope': 'Image construction only; cold boot and recovery must be verified on piano'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{r["sha256"]}  {r["file"]}\n' for r in outputs.values()))
    print(json.dumps({'output': str(out), 'images': list(outputs)}))


if __name__ == '__main__':
    main()
