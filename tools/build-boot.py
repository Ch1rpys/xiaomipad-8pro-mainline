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

from kernel_modules import runtime_metadata, subset_metadata
from initramfs_archive import read_newc, regular_file

CMDLINE_BASE = ('rdinit=/init console=ttyMSM0,115200n8 ignore_loglevel log_buf_len=2M '
                'panic=15')
ADSP_DTB = 'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-adsp-diag.dtb'
ADSP_CONFIG = ('CONFIG_QCOM_Q6V5_PAS=y', 'CONFIG_QCOM_SYSMON=y', 'CONFIG_QCOM_MDT_LOADER=y',
               'CONFIG_RPMSG_QCOM_GLINK_SMEM=y', 'CONFIG_QRTR=y', 'CONFIG_QRTR_SMD=y',
               'CONFIG_QCOM_PD_MAPPER=y', '# CONFIG_QCOM_PMIC_GLINK is not set',
               '# CONFIG_QCOM_FASTRPC is not set', '# CONFIG_QCOM_APR is not set')
DEFAULT_DTB = 'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano.dtb'
UFS_RO_DTB = 'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-ufs-ro-diag.dtb'
GPU_DTB = 'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-gpu-diag.dtb'
BT_DTB = 'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-bt-diag.dtb'
MIC_DTB = 'arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-mic-diag.dtb'
DRAFT_DTBS = ('arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-usb-role-diag.dtb',)
BT_CONFIG = ('CONFIG_RFKILL=y', 'CONFIG_BT=y', 'CONFIG_BT_LE=y', 'CONFIG_BT_QCA=y', 'CONFIG_BT_HCIUART=y',
             'CONFIG_BT_HCIUART_SERDEV=y', 'CONFIG_BT_HCIUART_QCA=y', 'CONFIG_POWER_SEQUENCING_QCOM_WCN=y')
# MDSS stays disabled while simpledrm scans out, so the GPU needs its own DRM device.
GPU_CMDLINE = 'msm.separate_gpu_kms=1'
UFS_NODES = ('/soc@0/ufs@1d84000', '/soc@0/phy@1d80000')
RAM_ONLY = ('# CONFIG_USB_DUMMY_HCD is not set', 'CONFIG_PSTORE_CONSOLE=y', 'CONFIG_PSTORE_RAM=y', '# CONFIG_MMC is not set',
            '# CONFIG_MTD is not set', '# CONFIG_BLK_DEV_NVME is not set')
UFS_RO_CONFIG = ('CONFIG_SCSI_UFSHCD=y', 'CONFIG_SCSI_UFSHCD_PLATFORM=y', 'CONFIG_SCSI_UFS_QCOM=y',
                 'CONFIG_PHY_QCOM_QMP_UFS=y', '# CONFIG_SCSI_UFS_CRYPTO is not set',
                 '# CONFIG_SCSI_UFS_BSG is not set', '# CONFIG_SCSI_UFS_HWMON is not set')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_errors(config, diagnostic):
    """Every mode except ufs-ro stays free of UFS; ufs-ro gets exactly the reviewed driver set."""
    storage = UFS_RO_CONFIG if diagnostic == 'ufs-ro' else ('# CONFIG_SCSI_UFSHCD is not set',)
    errors = [f'Missing RAM-only diagnostic configuration: {s}' for s in RAM_ONLY + storage if s not in config]
    if diagnostic in ('ncm', 'ubuntu', 'ufs-ro') and 'CONFIG_USB_CONFIGFS_NCM=y' not in config:
        errors.append('NCM requires the built-in kernel function')
    return errors


def dtb_source_error(diagnostic, dtb_source_name):
    if dtb_source_name in DRAFT_DTBS:
        return ('This DTB is offline preparation only: its restricted module/firmware payload '
                'and observation/recovery sequence are not integrated into the RAM runner yet')
    if (diagnostic == 'ufs-ro') != (dtb_source_name == UFS_RO_DTB):
        return f'The ufs-ro mode and {UFS_RO_DTB} are only used together'
    return None


def gpu_errors(config, dtb_source_name, firmware):
    if dtb_source_name != GPU_DTB:
        return []
    errors = [] if 'CONFIG_DRM_MSM=y' in config else ['The GPU DTB needs the built-in MSM driver (GPU OUT)']
    if not firmware:
        errors.append('The GPU DTB needs an initramfs built with FIRMWARE_DIR')
    return errors


def bt_errors(config, diagnostic, dtb_source_name):
    """The bt-diag DTB is only packaged with its built-in stack (bt-diag OUT) in the RAM desktop mode."""
    if dtb_source_name != BT_DTB:
        return []
    errors = [f'The bt-diag DTB needs the bt-diag OUT: {s}' for s in BT_CONFIG if s not in config]
    if diagnostic != 'ubuntu':
        errors.append('The bt-diag DTB is only used in the ubuntu mode (runtime firmware bundle)')
    return errors


def adsp_firmware_files():
    lock = json.loads((Path(__file__).resolve().parents[1] / 'firmware/piano-os3.0.303.0.json').read_text())
    return {f'qcom/sm8750/piano/{r["name"]}': (r['bytes'], r['sha256'])
            for r in lock['files'] if r['name'].startswith(('adsp.', 'adsp_dtb.'))}


def mic_errors(config, diagnostic, dtb_source_name, firmware, modules):
    if dtb_source_name != MIC_DTB:
        return [], None
    profile_path = Path(__file__).resolve().parents[1] / 'device/audio/diagnostic.json'
    profile = json.loads(profile_path.read_text())
    errors = []
    if diagnostic != 'ncm':
        errors.append('Mic probe first uses the 60-second NCM mode')
    for setting in ('CONFIG_MODULES=y', 'CONFIG_QCOM_Q6V5_PAS=m', 'CONFIG_QCOM_APR=m',
                    'CONFIG_QCOM_PD_MAPPER=m', 'CONFIG_SND_SOC_SC8280XP=m'):
        if setting not in config:
            errors.append(f'Mic probe needs explicit late module loading: {setting}')
    if any('CONFIG_' + name + '=y' in config for name in ('QCOM_PMIC_GLINK', 'QCOM_FASTRPC', 'BATTERY_QCOM_BATTMGR')):
        errors.append('Mic probe must not have forbidden consumers built in')
    if not modules or set(modules['requested']) != set(profile['module_order']):
        errors.append('Mic probe needs its exact requested module set')
    elif not set(profile['forbidden']) <= set(modules['forbidden']):
        errors.append('Mic module subset must exclude charger/USB/FastRPC consumers')
    topology = profile['topology']
    if sha(profile_path.with_name(topology['source'])) != topology['source_sha256']:
        errors.append('Mic topology source changed; rebuild and repin the diagnostic topology')
    expected = adsp_firmware_files()
    expected[topology['path']] = (topology['bytes'], topology['sha256'])
    actual = {r['path']: (r['size'], r['sha256']) for r in firmware}
    if actual != expected or len(actual) != len(firmware):
        errors.append('Mic probe needs exactly the locked ADSP firmware and capture topology')
    return errors, {'kind': profile['kind'], 'order': profile['module_order'],
                    'profile_sha256': sha(profile_path), 'scope': profile['scope']}


def adsp_errors(config, diagnostic, dtb_source_name, firmware):
    if dtb_source_name != ADSP_DTB:
        return []
    errors = [f'The ADSP DTB needs its isolated config: {s}' for s in ADSP_CONFIG if s not in config]
    if diagnostic != 'ncm':
        errors.append('The ADSP diagnostic uses the 60-second NCM mode')
    expected = adsp_firmware_files()
    actual = {r['path']: (r['size'], r['sha256']) for r in firmware}
    if len(actual) != len(firmware) or actual != expected:
        errors.append('ADSP initramfs firmware must exactly match the locked piano ADSP/DTB files')
    return errors


def firmware_manifest(cpio_bytes):
    """Return and verify the private firmware manifest and its actual archive bytes."""
    entries = read_newc(cpio_bytes)
    if 'etc/piano-firmware' not in entries:
        return '', []
    text = regular_file(entries, 'etc/piano-firmware').decode()
    rows = []
    for line in text.splitlines():
        path, size, digest = line.split(' ')
        if (not re.fullmatch(r'[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*', path) or
                any(p in ('.', '..') for p in Path(path).parts) or
                not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise ValueError('Invalid firmware manifest path/hash')
        data = regular_file(entries, 'lib/firmware/' + path)
        if len(data) != int(size) or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Delivered firmware bytes do not match manifest: {path}')
        rows.append({'path': path, 'size': int(size), 'sha256': digest})
    return text, rows


def module_manifest(cpio_bytes, build, build_result_sha256):
    """Verify delivered module bytes against both the subset and matching Kbuild output."""
    entries = read_newc(cpio_bytes)
    listing = list(entries)
    delivered = [n for n in listing if n.startswith(('lib/modules/', 'etc/piano-modules'))
                 or n == 'etc/modprobe.d/piano-ram-modules.conf']
    if 'etc/piano-modules.json' not in listing:
        if delivered:
            raise ValueError('Unmanifested module payload')
        return None
    extract = lambda n: regular_file(entries, n)
    manifest = json.loads(extract('etc/piano-modules.json'))
    subset_metadata(manifest)
    if (not build.get('modules') or manifest['kernel_commit'] != build['kernel_commit'] or
            manifest['kernel_release'] != build['modules']['kernel_release'] or
            manifest['kernel_sha256'] != build['files']['arch/arm64/boot/Image'] or
            manifest['config_sha256'] != build['files']['.config'] or
            manifest['build_result_sha256'] != build_result_sha256):
        raise ValueError('Module payload does not match this exact kernel build')
    metadata = runtime_metadata(manifest)
    regular_file(entries, 'bin/piano-modules')
    if not entries['bin/piano-modules'][0] & 0o111:
        raise ValueError('Module helper is not executable')
    wanted = set(manifest['files']) | metadata.keys() | {'bin/piano-modules'}
    if any(listing.count(n) != 1 for n in wanted):
        raise ValueError('Module payload file missing or duplicated')
    # Directories are also listed by cpio; allow only parents of verified files.
    parents = {str(parent) for n in manifest['files'] for parent in Path(n).parents}
    if set(delivered) - wanted - parents:
        raise ValueError('Unexpected files in module payload')
    for name, expected in manifest['files'].items():
        if hashlib.sha256(extract(name)).hexdigest() != expected:
            raise ValueError(f'Delivered module hash mismatch: {name}')
        if (re.search(r'\.ko(?:\.(?:gz|xz|zst))?$', name) or
                name.endswith(('/modules.builtin', '/modules.builtin.modinfo'))):
            relative = name.removeprefix(f'lib/modules/{manifest["kernel_release"]}/')
            if build['modules']['files'].get(relative) != expected:
                raise ValueError(f'Module differs from Kbuild receipt: {name}')
    for name, expected in metadata.items():
        if extract(name) != expected:
            raise ValueError(f'Delivered module policy/checksum mismatch: {name}')
    return manifest


def ufs_status(blob):
    import libfdt
    fdt = libfdt.Fdt(blob)
    status = []
    for node in UFS_NODES:
        try:
            status.append(fdt.getprop(fdt.path_offset(node), 'status').as_str())
        except libfdt.FdtException:
            status.append(None)
    return status


def ufs_dtb_errors(default_blob, variant_blob, packaging_blob):
    """The default board DTB of the same build must still keep both UFS nodes disabled."""
    errors = []
    for label, blob, expected in (('default kernel DTB', default_blob, 'disabled'),
                                  ('ufs-ro kernel DTB', variant_blob, 'okay'),
                                  ('packaging DTB', packaging_blob, 'okay')):
        status = ufs_status(blob)
        if status != [expected, expected]:
            errors.append(f'{label}: UFS host/PHY status {status}, expected {expected}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', type=Path, required=True)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--initramfs', type=Path, required=True)
    parser.add_argument('--dtb', type=Path, required=True)
    parser.add_argument('--mkbootimg', type=Path, required=True)
    parser.add_argument('--dtb-source-name', default=DEFAULT_DTB,
                        help='Kernel DTB in build-result.json that the packaging DTB was prepared from')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--boot-id', default='mainline-r1',
                        help='Short experiment label recorded in the kernel command line')
    parser.add_argument('--diagnostic', choices=('console', 'acm', 'ncm', 'ubuntu', 'ufs-ro'), default='console',
                        help='60-second diagnostics, bounded two-stage RAM Ubuntu, or the 60-second '
                             'NCM read-only UFS identification (host-sent stage)')
    parser.add_argument('--rootfs-sha256', help='Exact SquashFS input for the ubuntu mode')
    parser.add_argument('--root-transport', choices=('http', 'nbd'), default='http',
                        help='Explicit root transport, never an automatic fallback')
    parser.add_argument('--session-seconds', type=int, default=300,
                        help='Bounded Ubuntu observation window after handoff (60-900 seconds)')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', args.boot_id):
        parser.error('boot-id must be a 1-64 character ASCII experiment label')
    ubuntu = args.diagnostic == 'ubuntu'
    if ubuntu and not re.fullmatch(r'[0-9a-f]{64}', args.rootfs_sha256 or ''):
        parser.error('ubuntu mode requires the exact rootfs SHA-256')
    if args.rootfs_sha256 and not ubuntu:
        parser.error('rootfs-sha256 is only used by the ubuntu mode')
    if not 60 <= args.session_seconds <= 900:
        parser.error('session-seconds must be between 60 and 900')
    if error := dtb_source_error(args.diagnostic, args.dtb_source_name):
        parser.error(error)
    timeout = 600 if ubuntu else 60
    cmdline = (f'{CMDLINE_BASE} piano.boot={args.boot_id} '
               f'piano.diag={args.diagnostic} piano.diag_timeout={timeout}')
    if args.dtb_source_name == GPU_DTB:
        cmdline += f' {GPU_CMDLINE}'
    if args.diagnostic == 'ufs-ro':
        # Documents intent only: the RAM root is the initramfs and has no root= device.
        cmdline += ' ro'
    if ubuntu:
        cmdline += (f' piano.rootfs.sha256={args.rootfs_sha256} piano.session={args.session_seconds}'
                    f' piano.rootfs.transport={args.root_transport}')
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
    if args.dtb_source_name not in build['files']:
        parser.error(f'Kernel build did not record {args.dtb_source_name}')
    if overlay['inputs_sha256']['mainline_dtb'] != build['files'][args.dtb_source_name]:
        parser.error('Packaging DTB was built from another kernel DTB')
    config = (kout / '.config').read_text().splitlines()
    if errors := config_errors(config, args.diagnostic):
        parser.error('; '.join(errors))
    if args.diagnostic == 'ufs-ro':
        if DEFAULT_DTB not in build['files']:
            parser.error('Kernel build did not record the default piano DTB')
        if errors := ufs_dtb_errors((kout / DEFAULT_DTB).read_bytes(), (kout / UFS_RO_DTB).read_bytes(),
                                    args.dtb.read_bytes()):
            parser.error('; '.join(errors))
    if ubuntu:
        for setting in ('CONFIG_OVERLAY_FS=y', 'CONFIG_SQUASHFS=y',
                        'CONFIG_SQUASHFS_ZSTD=y', 'CONFIG_SQUASHFS_XATTR=y', 'CONFIG_BLK_DEV_LOOP=y'):
            if setting not in config:
                parser.error(f'Missing RAM-root dependency: {setting}')
        if args.root_transport == 'nbd' and 'CONFIG_BLK_DEV_NBD=y' not in config:
            parser.error('NBD root requires the built-in upstream NBD client')
    image = kout / 'arch/arm64/boot/Image'
    cpio_bytes = gzip.decompress(args.initramfs.read_bytes())
    ram_build_id = subprocess.check_output(
        ['cpio', '--extract', '--to-stdout', '--quiet', 'etc/build-id'], input=cpio_bytes).decode().strip()
    if not re.fullmatch(r'[0-9a-f]{64}', ram_build_id):
        parser.error('The ramdisk must contain its exact diagnostic build-id')
    firmware_text, firmware = firmware_manifest(cpio_bytes)
    modules = module_manifest(cpio_bytes, build, sha(kout / 'build-result.json'))
    if errors := gpu_errors(config, args.dtb_source_name, firmware):
        parser.error('; '.join(errors))
    if errors := bt_errors(config, args.diagnostic, args.dtb_source_name):
        parser.error('; '.join(errors))
    if errors := adsp_errors(config, args.diagnostic, args.dtb_source_name, firmware):
        parser.error('; '.join(errors))
    errors, activation = mic_errors(config, args.diagnostic, args.dtb_source_name, firmware, modules)
    if errors:
        parser.error('; '.join(errors))
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
        'timeout_seconds': timeout,
        'ram_build_id': ram_build_id,
        'dtb_source': args.dtb_source_name,
        'inputs_sha256': {'Image': sha(image), 'dtb': sha(args.dtb),
                          'initramfs': sha(args.initramfs), 'mkbootimg': sha(args.mkbootimg),
                          'config': sha(kout / '.config')},
        'scope': ('fastboot boot only; RAM boot, UFS probe; the host-sent stage sets every UFS block device '
                  'read-only before reading; no mount, no native panel support'
                  if args.diagnostic == 'ufs-ro' else
                  'fastboot boot only; diagnostic userspace, internal UFS/MMC/MTD/NVMe disabled and no native panel support; firmware framebuffer support is candidate-specific'),
        'recovery': f'{timeout}-second initial PID1 timer and panic=15; Ubuntu mode hands off to a {args.session_seconds}-second early systemd timer; early hangs may require manual reset',
    }
    if modules:
        manifest['modules'] = modules
    if activation:
        manifest['module_activation'] = activation
    if firmware:
        # Identities only; the private bytes stay in the initramfs and its private source.
        manifest['inputs_sha256']['firmware_manifest'] = hashlib.sha256(firmware_text.encode()).hexdigest()
        manifest['firmware'] = firmware
    if args.dtb_source_name == BT_DTB:
        manifest['bt_diag'] = {'dtb_sha256': build['files'][BT_DTB], 'config_fragments': build.get('config_fragments'),
                               'firmware': 'runtime bundle from run-mainline-probe.py --bt-firmware-dir, not in the image'}
    if args.dtb_source_name == GPU_DTB:
        manifest['gpu_diag'] = {'cmdline': GPU_CMDLINE, 'dtb_sha256': build['files'][GPU_DTB],
                                'config_fragments': build.get('config_fragments')}
    if ubuntu:
        manifest['rootfs_sha256'] = args.rootfs_sha256
        manifest['session_seconds'] = args.session_seconds
        manifest['root_transport'] = args.root_transport
        manifest['root_verification'] = ('HOST_SHA256_AND_READONLY_NAMED_EXPORT' if args.root_transport == 'nbd'
                                         else 'HOST_AND_GUEST_FULL_SHA256')
    if args.diagnostic == 'ufs-ro':
        manifest['ufs_ro'] = {'default_dtb': DEFAULT_DTB, 'default_dtb_sha256': build['files'][DEFAULT_DTB],
                              'default_dtb_ufs_status': 'disabled', 'variant_dtb_sha256': build['files'][UFS_RO_DTB],
                              'config_fragments': build.get('config_fragments')}
    if args.diagnostic in ('ncm', 'ubuntu', 'ufs-ro'):
        network = Path(__file__).resolve().parent.parent / 'initramfs/network.json'
        manifest['network'] = json.loads(network.read_text())
        manifest['inputs_sha256']['network'] = sha(network)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
