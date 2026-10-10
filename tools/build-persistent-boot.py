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

# Debug-only observation of a boot that stops before userspace. console-ramoops
# (pstore) is always a console; dropping the 115200 serial console keeps the
# extra output from adding seconds of synchronous UART time, so the pstore copy
# of the log carries every level, each initcall and every clk disable/unprepare
# with its completion. CONFIG_NULL_TTY is off, so ttynull only names "no tty".
DEBUG_BOOT_TRACE = ('console=ttynull ignore_loglevel initcall_debug tp_printk trace_event='
                    'clk:clk_disable,clk:clk_disable_complete,clk:clk_unprepare,clk:clk_unprepare_complete')


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def kernel_release(path):
    """Release string of an uncompressed arm64 Image, from its linux_banner."""
    match = re.search(rb'Linux version ([0-9][A-Za-z0-9.+-]*) \(', Path(path).read_bytes())
    return match[1].decode() if match else None


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
    root = p.add_mutually_exclusive_group(required=True)
    root.add_argument('--root-partuuid', type=uuid.UUID, help='The root partition of this unit')
    root.add_argument('--root-partlabel',
                      help='GPT name of the root partition (linux_rootfs): a set that boots on any unit')
    p.add_argument('--kernel-release', help='Expected release; the Image banner must carry it')
    p.add_argument('--bt-address-file', type=Path)
    p.add_argument('--wlan-address-file', type=Path,
                   help='Private aa:bb:cc:dd:ee:ff of this unit, set as the WCN7860 local-mac-address')
    p.add_argument('--no-serial', action='store_true',
                   help='Leave androidboot.serialno to ABL, which appends it to every command line; '
                        'a set that is not bound to one unit')
    p.add_argument('--debug', action='store_true')
    p.add_argument('--debug-timeout', type=int, default=0)
    p.add_argument('--module-blacklist', help='Explicit comma-separated module control for a debug boot')
    p.add_argument('--modprobe-blacklist',
                   help='Debug boot only: kmod modprobe.blacklist= (stops alias autoload; an explicit insmod still loads)')
    p.add_argument('--debug-boot-trace', action='store_true',
                   help='Debug boot only: replace the serial console by DEBUG_BOOT_TRACE')
    a = p.parse_args()
    if a.debug_timeout and (not a.debug or not 60 <= a.debug_timeout <= 900):
        p.error('A 60–900 second timeout is only available for explicit debug boots')
    for control in (a.module_blacklist, a.modprobe_blacklist):
        if control and (not a.debug or not re.fullmatch(r'[a-z0-9_]+(?:,[a-z0-9_]+)*', control)):
            p.error('Module controls require an explicit debug boot and valid module names')
    if a.debug_boot_trace and not a.debug:
        p.error('The boot trace console is only available for explicit debug boots')
    if a.root_partlabel is not None and not re.fullmatch(r'[A-Za-z0-9_.-]{1,36}', a.root_partlabel):
        p.error('A GPT partition name of 1-36 letters, digits, "_", "." or "-" is required')
    root_spec = (f'PARTUUID={a.root_partuuid}' if a.root_partuuid is not None else f'PARTLABEL={a.root_partlabel}')
    release = kernel_release(a.kernel)
    if not release:
        p.error('Kernel has no Linux version banner; expected an uncompressed arm64 Image')
    if a.kernel_release and a.kernel_release != release:
        p.error(f'Kernel banner is {release}, not {a.kernel_release}')
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
    if a.wlan_address_file:
        address = a.wlan_address_file.read_text().strip()
        if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
            p.error('Invalid local WLAN address')
        raw = bytes.fromhex(address.replace(':', ''))
        if raw == bytes(6) or raw[0] & 1:
            p.error('WLAN address is not a usable unicast address')
        node = '/soc@0/pcie@1c00000/pcie@0/wifi@0'
        compatible = subprocess.check_output(['fdtget', '-t', 's', str(dtb), node, 'compatible'], text=True).strip()
        if compatible != 'pci17cb,110e':
            p.error('Expected the piano WCN7860 WLAN node')
        # ath12k reads it with device_get_mac_address() when the card reports none; byte order as written.
        subprocess.run(['fdtput', '-t', 'bx', str(dtb), node, 'local-mac-address',
                        *[f'{b:02x}' for b in raw]], check=True)
    console = DEBUG_BOOT_TRACE if a.debug_boot_trace else 'console=ttyMSM0,115200n8'
    cmdline = (f'root={root_spec} rootfstype=ext4 rw rootwait '
               f'{console} log_buf_len=2M panic=15 '
               'msm.separate_gpu_kms=1 piano.boot=persistent systemd.gpt_auto=0 bootconfig')
    # V4 may expose the firmware serial only in bootconfig. Keep the explicit
    # development gadget bound to the locally verified installation profile.
    # ABL also appends androidboot.serialno to the kernel command line it
    # passes (seen on piano); --no-serial relies on that copy alone.
    if not a.no_serial:
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
    if a.modprobe_blacklist:
        cmdline += ' modprobe.blacklist=' + a.modprobe_blacklist
    # The v2 RAM check carries the command line in its 512-byte cmdline field; mkbootimg puts
    # any rest in extra_cmdline, which piano's ABL drops (speakers-1, 2026-10-10: a 593-byte
    # line arrived cut at byte 511, losing part of modprobe.blacklist=).
    if len(cmdline.encode()) > 511:
        raise ValueError(f'command line is {len(cmdline.encode())} bytes; the RAM check keeps only 511')
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
    manifest = {'kind': 'piano-persistent-v4', 'kernel_release': release,
                'cmdline': cmdline, 'root': root_spec,
                'root_partuuid': str(a.root_partuuid) if a.root_partuuid is not None else None,
                'serial_in_cmdline': not a.no_serial,
                'debug': a.debug, 'debug_timeout': a.debug_timeout,
                'inputs': {n: sha(getattr(a, n)) for n in ('kernel', 'dtb', 'initrd', 'profile', 'mkbootimg', 'avbtool')},
                'private_bt_address_injected': bool(a.bt_address_file),
                'private_wlan_address_injected': bool(a.wlan_address_file), 'effective_dtb_sha256': sha(dtb),
                'outputs': outputs, 'ram_image': {'file': ram.name, 'sha256': sha(ram)},
                'scope': 'Image construction only; cold boot and recovery must be verified on piano'}
    if a.debug_boot_trace:
        manifest['debug_boot_trace'] = DEBUG_BOOT_TRACE
    if a.modprobe_blacklist:
        manifest['modprobe_blacklist'] = a.modprobe_blacklist
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{r["sha256"]}  {r["file"]}\n' for r in outputs.values()))
    print(json.dumps({'output': str(out), 'images': list(outputs)}))


if __name__ == '__main__':
    main()
