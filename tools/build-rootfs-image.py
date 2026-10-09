#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the release root filesystem image from the pinned Desktop base and the piano packages.

No host root: sqfs2tar streams the pristine Desktop SquashFS into upstream
mke2fs -d (libarchive), creating the ext4 at the full partition size.  A
disposable QEMU ARM64 guest, whose own root is that SquashFS mounted
read-only, then runs rootfs-image-guest.sh as root: the steps of
docs/AGENT-GUIDE.md section 4.4 in a chroot of the target (policy-rc.d,
SYSTEMD_OFFLINE=1 dpkg --install, distribution kernel hooks and dracut) and
the release boot image set.  The target never boots.

The image is for any unit: fstab and /etc/piano/layout.json name the fixed
GPT partitions linux_rootfs and linux_data; the boot set is built with
--root-partlabel and --no-serial from a boot profile reduced to the stock
build's fields, without Bluetooth or Wi-Fi addresses.  There is no account
(GNOME Initial Setup creates the first one), no machine ID, no SSH host keys
and no per-unit file in /etc/piano.  Outputs: root.ext4 (sparse),
root.sparse.img (img2simg), SHA256SUMS, manifest.json, verification.json.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
import uuid

REPO = Path(__file__).resolve().parents[1]
ROOT_PARTLABEL = 'linux_rootfs'
DATA_PARTLABEL = 'linux_data'
FSTAB = (f'PARTLABEL={ROOT_PARTLABEL} / ext4 defaults,noatime 0 1\n'
         f'PARTLABEL={DATA_PARTLABEL} /home ext4 defaults,noatime 0 2\n')
LAYOUT = {'root_partlabel': ROOT_PARTLABEL, 'data_partlabel': DATA_PARTLABEL}
# The profile fields build-persistent-boot.py reads.  They come from the stock
# build (header geometry, rollback indices, AVB properties); the serial, slot
# observations and image hashes of the unit they were read from are dropped.
PROFILE_FIELDS = {
    'boot': ('header_version', 'capacity', 'rollback_index', 'avb_properties'),
    'init_boot': ('header_version', 'capacity', 'rollback_index', 'avb_properties'),
    'vendor_boot': ('header_version', 'capacity', 'rollback_index', 'avb_properties',
                    'page_size', 'kernel_addr', 'ramdisk_addr', 'tags_addr', 'dtb_addr'),
}
PIANO_PACKAGES = ('piano-device-support', 'piano-local-firmware', 'piano-mesa', 'piano-ubuntu-desktop')
UNITS_ENABLED = {'piano-slot-success.service': 'enabled', 'piano-devmode.service': 'disabled',
                 'ssh.socket': 'disabled', 'ssh.service': 'disabled'}
SERIALS = ('piano-helper', 'piano-target', 'piano-inputs', 'piano-result')


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def portable(value, out):
    """A command argument without host paths: the output directory and inputs below $HOME by name only."""
    text = str(value).replace(str(out), '<output>')
    return re.sub(re.escape(str(Path.home())) + r'/[^\s,]*/([^/\s,]+)', r'<input>/\1', text)


def release_profile(unit):
    profile = {name: {k: unit[name][k] for k in fields} for name, fields in PROFILE_FIELDS.items()}
    profile['scope'] = ('Stock boot image fields for build-persistent-boot.py --no-serial; '
                        'no serial or other data of the unit it was read from')
    return profile


def deb_fields(path):
    text = subprocess.check_output(['dpkg-deb', '--field', str(path), 'Package', 'Version', 'Architecture'],
                                   text=True)
    return dict(line.split(': ', 1) for line in text.splitlines())


def extract_member(deb, name, dest):
    """One regular file from a deb's data archive, without unpacking anything else."""
    with subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(deb)], stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
            for member in archive:
                if member.name.removeprefix('./') == name and member.isreg():
                    with archive.extractfile(member) as src, dest.open('wb') as out:
                        shutil.copyfileobj(src, out)
                    break
            else:
                raise ValueError(f'{deb.name} has no {name}')
        proc.stdout.close()
        proc.kill()
    return dest


def scan_base(sqfs2tar, squashfs):
    """Root mtime and the file capabilities of the base, from the same TAR stream mke2fs reads."""
    caps = {}
    root_mtime = None
    with subprocess.Popen([str(sqfs2tar), '--root-becomes', '.', '--no-skip', str(squashfs)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
            for member in archive:
                if root_mtime is None:
                    if member.name not in ('.', './') or not member.isdir():
                        raise ValueError('sqfs2tar output must start with the root directory')
                    root_mtime = int(member.mtime)
                value = member.pax_headers.get('SCHILY.xattr.security.capability')
                if value is not None:
                    caps[member.name.removeprefix('./')] = value.encode('utf-8', 'surrogateescape').hex()
        if proc.wait():
            raise RuntimeError('sqfs2tar failed')
    return root_mtime, caps


class Debugfs:
    """Read-only queries of an ext4 file with the pinned debugfs."""

    def __init__(self, debugfs, image, env):
        self.debugfs, self.image, self.env = str(debugfs), str(image), env

    def run(self, command):
        proc = subprocess.run([self.debugfs, '-R', command, self.image], capture_output=True, env=self.env)
        return proc.stdout, proc.stderr.decode(errors='replace')

    def cat(self, path):
        data, err = self.run(f'cat {path}')
        if 'File not found' in err:
            return None
        return data

    def names(self, path):
        data, err = self.run(f'ls -p {path}')
        if 'File not found' in err:
            return None
        return sorted({line.split('/')[5] for line in data.decode().splitlines()
                       if line.count('/') >= 6 and line.split('/')[5] not in ('.', '..')})

    def exists(self, path):
        return 'File not found' not in self.run(f'stat {path}')[1]

    def size(self, path):
        data, _ = self.run(f'stat {path}')
        match = re.search(rb'Size: (\d+)', data)
        return int(match[1]) if match else None

    def dump_sha(self, path, scratch):
        target = scratch / 'dump'
        self.run(f'dump {path} {target}')
        if not target.exists():
            return None
        digest = sha(target)
        target.unlink()
        return digest

    def xattr(self, path, name, scratch):
        target = scratch / 'xattr'
        self.run(f'ea_get -f {target} {path} {name}')
        if not target.exists():
            return None
        value = target.read_bytes().hex()
        target.unlink()
        return value


def dpkg_status(text):
    packages = {}
    for paragraph in text.split('\n\n'):
        fields = dict(re.findall(r'^([A-Za-z-]+): (.*)$', paragraph, re.M))
        if 'Package' in fields:
            packages[fields['Package']] = (fields.get('Status'), fields.get('Version'))
    return packages


def verify(fs, scratch, expected_packages, release, caps, set_hashes, boot_hashes):
    """The offline release checks of docs/RELEASE.md on the finished image."""
    checks = {}
    status = dpkg_status(fs.cat('/var/lib/dpkg/status').decode())
    checks['packages_installed'] = {p: status.get(p) == ('install ok installed', v)
                                    for p, v in sorted(expected_packages.items())}
    # Fully installed or removed with configuration kept: nothing half-installed or pending triggers.
    checks['no_package_in_other_state'] = sorted(
        p for p, (s, _) in status.items()
        if s.split()[1:] not in (['ok', 'installed'], ['ok', 'config-files'], ['ok', 'not-installed'])) == []
    checks['gnome_initial_setup_installed'] = (status.get('gnome-initial-setup', ('',))[0] == 'install ok installed'
                                               and fs.exists('/usr/libexec/gnome-initial-setup'))
    custom = fs.cat('/etc/gdm3/custom.conf').decode()
    active = [l.strip().replace(' ', '') for l in custom.splitlines() if l.strip() and not l.lstrip().startswith('#')]
    checks['gdm_no_autologin_initial_setup_not_disabled'] = not any(
        l.startswith(('AutomaticLogin', 'TimedLogin')) or l.lower() == 'initialsetupenable=false' for l in active)
    passwd = fs.cat('/etc/passwd').decode()
    users = [l.split(':')[0] for l in passwd.splitlines() if l and 1000 <= int(l.split(':')[2]) < 65534]
    checks['no_user_accounts'] = users == []
    shadow = fs.cat('/etc/shadow').decode()
    root = next(l for l in shadow.splitlines() if l.startswith('root:'))
    checks['root_password_locked'] = root.split(':')[1][:1] in ('!', '*')
    checks['home_empty'] = fs.names('/home') == []
    checks['machine_id_empty'] = fs.size('/etc/machine-id') == 0
    dbus = fs.run('stat /var/lib/dbus/machine-id')[0]
    checks['dbus_machine_id_absent_empty_or_link'] = (not dbus or b'Type: symlink' in dbus
                                                       or fs.size('/var/lib/dbus/machine-id') == 0)
    checks['no_ssh_host_keys'] = [n for n in fs.names('/etc/ssh') if n.startswith('ssh_host_')] == []
    checks['etc_piano_only_layout'] = fs.names('/etc/piano') == ['layout.json']
    mode = fs.run('stat /etc/piano/layout.json')[0]
    checks['layout_root_0600'] = re.search(rb'Mode: +0600', mode) is not None and re.search(rb'User: +0 ', mode) is not None
    checks['layout_by_partlabel'] = json.loads(fs.cat('/etc/piano/layout.json')) == LAYOUT
    checks['fstab_by_partlabel'] = fs.cat('/etc/fstab') == FSTAB.encode()
    checks['no_install_leftovers'] = not any(fs.exists(p) for p in (
        '/var/cache/piano-install', '/usr/sbin/policy-rc.d', '/etc/initramfs-tools/update-initramfs.conf',
        '/var/lib/systemd/random-seed'))
    checks['apt_policy'] = (fs.cat('/etc/apt/sources.list.d/ubuntu.sources') == (REPO / 'ubuntu/26.04.sources').read_bytes()
                            and not fs.exists('/etc/apt/sources.list.d/cdrom.sources')
                            and fs.exists('/etc/cloud/cloud-init.disabled'))
    checks['apt_caches_clean'] = not [n for n in fs.names('/var/cache/apt/archives') or [] if n.endswith('.deb')] and not any(
        fs.exists('/var/cache/apt/' + n) for n in ('pkgcache.bin', 'srcpkgcache.bin'))
    journal = fs.names('/var/log/journal')
    checks['journal_empty'] = journal in (None, [])
    wants = {
        'piano-slot-success.service': '/etc/systemd/system/multi-user.target.wants/piano-slot-success.service',
        'piano-devmode.service': '/etc/systemd/system/usb-gadget.target.wants/piano-devmode.service',
        'ssh.socket': '/etc/systemd/system/sockets.target.wants/ssh.socket',
        'ssh.service': '/etc/systemd/system/multi-user.target.wants/ssh.service',
    }
    checks['unit_enablement'] = {u: fs.exists(p) == (UNITS_ENABLED[u] == 'enabled') for u, p in wants.items()}
    checks['kernel_files'] = {f'/boot/{n}-{release}': fs.dump_sha(f'/boot/{n}-{release}', scratch) == boot_hashes.get(
        f'/boot/{n}-{release}') for n in ('vmlinuz', 'initrd.img')}
    store = '/var/lib/piano/switch'
    checks['store_only_ubuntu_set'] = fs.names(store) == ['ubuntu']
    sums = fs.cat(f'{store}/ubuntu/SHA256SUMS').decode()
    listed = dict(reversed(line.split()) for line in sums.splitlines())
    checks['store_set_matches_sha256sums'] = sorted(listed) == ['boot.img', 'init_boot.img', 'vendor_boot.img'] and all(
        fs.dump_sha(f'{store}/ubuntu/{n}', scratch) == h == set_hashes[n] for n, h in listed.items())
    checks['file_capabilities_kept'] = {p: fs.xattr('/' + p, 'security.capability', scratch) == v
                                        for p, v in sorted(caps.items())}

    def passed(value):
        return all(value.values()) if isinstance(value, dict) else bool(value)
    return {'passed': all(passed(v) for v in checks.values()), 'checks': checks,
            'failed': sorted(k for k, v in checks.items() if not passed(v))}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--squashfs', type=Path, required=True, help='Pristine Desktop SquashFS (build.zh-CN.md)')
    ap.add_argument('--squashfs-sha256', required=True)
    ap.add_argument('--sqfs2tar', type=Path, required=True, help='squashfs-tools-ng 1.2 sqfs2tar')
    ap.add_argument('--mke2fs', type=Path, required=True, help='mke2fs 1.47.4 with libarchive')
    ap.add_argument('--mke2fs-config', type=Path, required=True)
    ap.add_argument('--e2fsck', type=Path, required=True)
    ap.add_argument('--debugfs', type=Path, required=True)
    ap.add_argument('--qemu', type=Path, required=True, help='qemu-system-aarch64')
    ap.add_argument('--kernel-deb', type=Path, required=True)
    ap.add_argument('--deb', type=Path, action='append', required=True,
                    help='piano-device-support, piano-local-firmware, piano-mesa, piano-ubuntu-desktop')
    ap.add_argument('--apt-manifest', type=Path, required=True,
                    help='prepare-ubuntu-apt.py --download manifest of the Ubuntu packages to add')
    ap.add_argument('--boot-profile', type=Path, required=True, help='Boot profile read from a stock unit')
    ap.add_argument('--boot-key', type=Path, required=True, help='AVB signing key of the release set')
    ap.add_argument('--release-name', default='v0.1.0-preview')
    ap.add_argument('--size-mib', type=int, default=61440, help='linux_rootfs size (60 GiB)')
    ap.add_argument('--smp', type=int, default=8)
    ap.add_argument('--memory-mib', type=int, default=4096)
    ap.add_argument('--timeout', type=int, default=5400, help='Host budget for the QEMU guest in seconds')
    ap.add_argument('--output', type=Path, required=True, help='New output directory')
    a = ap.parse_args()
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+(-[a-z0-9.]+)?', a.release_name):
        ap.error('Release names look like v0.1.0-preview')
    if a.size_mib < 16384:
        ap.error('The root needs at least 16 GiB')
    started = time.monotonic()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, MKE2FS_CONFIG=str(a.mke2fs_config.resolve()), LC_ALL='C.UTF-8', LANGUAGE='C')
    result = {'state': 'BUILDING', 'release_name': a.release_name, 'tool_sha256': sha(Path(__file__)),
              'guest_script_sha256': sha(Path(__file__).with_name('rootfs-image-guest.sh')),
              'scope': ('Root filesystem image for any piano unit, built offline; not booted on a tablet by this tool'),
              'timings_seconds': {}}

    def save():
        (out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')

    def lap(name, since):
        result['timings_seconds'][name] = round(time.monotonic() - since, 1)
        save()
        return time.monotonic()

    save()
    try:
        # Inputs, all by hash.
        if sha(a.squashfs) != a.squashfs_sha256:
            raise ValueError('Desktop SquashFS hash mismatch')
        unit_profile = json.loads(a.boot_profile.read_text())
        profile = release_profile(unit_profile)
        (out / 'boot-profile.json').write_text(json.dumps(profile, indent=2) + '\n')
        apt = json.loads(a.apt_manifest.read_text())
        if apt['state'] != 'DOWNLOADED_NOT_INSTALLED' or apt['rootfs_sha256'] != a.squashfs_sha256:
            raise ValueError('APT manifest must be a download resolved against this SquashFS')
        debs = []
        for entry in apt['debs']:
            path = a.apt_manifest.parent / entry['file']
            if sha(path) != entry['sha256']:
                raise ValueError(f'APT package changed after download: {path.name}')
            debs.append((path, {'package': entry['package'], 'version': entry['version'],
                                'architecture': entry['architecture'], 'file': path.name, 'sha256': entry['sha256'],
                                'source': f'Ubuntu snapshot {apt["snapshot"]}'}))
        kernel = deb_fields(a.kernel_deb)
        match = re.fullmatch(r'linux-image-(.+-piano[0-9]+)', kernel['Package'])
        if not match:
            raise ValueError('The kernel package must be a released linux-image-<version>-piano<ABI>')
        release = match[1]
        for path in [a.kernel_deb, *a.deb]:
            fields = deb_fields(path)
            debs.append((path, {'package': fields['Package'], 'version': fields['Version'],
                                'architecture': fields['Architecture'], 'file': path.name, 'sha256': sha(path),
                                'source': 'piano'}))
        # Host paths stay in this local file; manifest.json is published with the release.
        (out / 'inputs-local.json').write_text(json.dumps(
            {d['file']: str(path.resolve()) for path, d in debs}, indent=2) + '\n')
        names = [d['package'] for _, d in debs]
        if len(names) != len(set(names)) or not set(PIANO_PACKAGES) <= set(names):
            raise ValueError(f'Need exactly one of each package and all of {PIANO_PACKAGES}')
        result.update(kernel_release=release, squashfs_sha256=a.squashfs_sha256,
                      apt_manifest_sha256=sha(a.apt_manifest), apt_snapshot=apt['snapshot'],
                      boot_profile_sha256=sha(out / 'boot-profile.json'),
                      boot_key_public_sha256=hashlib.sha256(subprocess.check_output(
                          ['openssl', 'pkey', '-in', str(a.boot_key), '-pubout', '-outform', 'DER'])).hexdigest(),
                      qemu_version=subprocess.check_output([str(a.qemu), '--version'], text=True).splitlines()[0],
                      packages=[d for _, d in debs],
                      tools={n: sha(getattr(a, n)) for n in ('sqfs2tar', 'mke2fs', 'mke2fs_config', 'e2fsck',
                                                             'debugfs', 'qemu')},
                      img2simg_version=subprocess.run(['dpkg-query', '-W', '-f', '${Version}',
                                                       'android-sdk-libsparse-utils'],
                                                      capture_output=True, text=True).stdout or None,
                      root_partlabel=ROOT_PARTLABEL, data_partlabel=DATA_PARTLABEL, fstab=FSTAB, layout=LAYOUT)
        save()

        # The base ext4 at the full partition size, from the SquashFS TAR stream.
        t = time.monotonic()
        print('Scanning the base for file capabilities', flush=True)
        epoch, caps = scan_base(a.sqfs2tar, a.squashfs)
        result.update(base_epoch=epoch, base_file_capabilities=len(caps))
        t = lap('scan_base', t)
        fs_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f'piano-rootfs:{a.release_name}')
        image = out / 'root.ext4.partial'
        with image.open('xb') as f:
            f.truncate(a.size_mib << 20)
        mke2fs = [str(a.mke2fs.resolve()), '-q', '-t', 'ext4', '-b', '4096', '-m', '0',
                  '-U', str(fs_uuid), '-L', ROOT_PARTLABEL,
                  '-E', f'lazy_itable_init=0,lazy_journal_init=0,root_owner=0:0,hash_seed={fs_uuid}',
                  '-d', '-', str(image)]
        result.update(filesystem_uuid=str(fs_uuid), filesystem_bytes=a.size_mib << 20,
                      mke2fs_command=[portable(w, out) for w in mke2fs])
        save()
        print('Populating the ext4 from the SquashFS TAR stream', flush=True)
        with (out / 'mke2fs.log').open('wb') as log:
            source = subprocess.Popen([str(a.sqfs2tar), '--root-becomes', '.', '--no-skip', str(a.squashfs)],
                                      stdout=subprocess.PIPE, stderr=log)
            sink = subprocess.Popen(mke2fs, stdin=source.stdout, stdout=log, stderr=subprocess.STDOUT,
                                    env=dict(env, E2FSPROGS_FAKE_TIME=str(epoch)))
            source.stdout.close()
            if sink.wait() or source.wait():
                raise RuntimeError('sqfs2tar | mke2fs failed; see mke2fs.log')
        t = lap('mke2fs', t)

        # Guest inputs: one TAR on a read-only disk.  It holds the release key and is deleted afterwards.
        guest_kernel = extract_member(a.kernel_deb, f'boot/vmlinuz-{release}', out / f'vmlinuz-{release}')
        inputs = out / 'inputs.tar'
        epoch_files = {
            'params.sh': f'RELEASE={release}\nROOT_PARTLABEL={ROOT_PARTLABEL}\n'.encode(),
            'guest.sh': Path(__file__).with_name('rootfs-image-guest.sh').read_bytes(),
            'files/etc/apt/sources.list.d/ubuntu.sources': (REPO / 'ubuntu/26.04.sources').read_bytes(),
            'files/etc/piano/layout.json': (json.dumps(LAYOUT, indent=2) + '\n').encode(),
            'files/etc/fstab': FSTAB.encode(),
            'release/boot-profile.json': (out / 'boot-profile.json').read_bytes(),
            'release/boot-signing.pem': a.boot_key.read_bytes(),
        }
        with tarfile.open(inputs, 'w', format=tarfile.PAX_FORMAT) as tar:
            def add(name, data=None, path=None):
                info = tarfile.TarInfo(name)
                info.mtime, info.mode = epoch, 0o600 if name.endswith('.pem') else 0o644
                if path is not None:
                    info.size = path.stat().st_size
                    with path.open('rb') as src:
                        tar.addfile(info, src)
                else:
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            for name, data in epoch_files.items():
                add(name, data)
            for path, _ in debs:
                add('debs/' + path.name.replace('%3a', '_'), path=path)
        result_disk = out / 'result.raw'
        with result_disk.open('xb') as f:
            f.truncate(1 << 30)
        run = ("/bin/sh -c 'mkdir -p /run/piano-inputs && tar -xf /dev/vdc -C /run/piano-inputs "
               "&& exec /bin/sh /run/piano-inputs/guest.sh'")
        # The helper skips AppArmor: compiling the Desktop profiles under TCG takes many minutes, and
        # nothing in the chroot steps depends on it.  The target's own policy is untouched.
        cmdline = ('console=ttyAMA0 root=/dev/vda rootfstype=squashfs ro rootwait panic=-1 apparmor=0 '
                   'systemd.unit=kernel-command-line.target systemd.run_success_action=poweroff '
                   f'systemd.run_failure_action=poweroff systemd.run="{run}"')
        drives = [(a.squashfs.resolve(), 'readonly=on'), (image, 'cache=unsafe'),
                  (inputs, 'readonly=on'), (result_disk, '')]
        command = [str(a.qemu), '-machine', 'virt', '-cpu', 'max', '-accel', 'tcg,thread=multi',
                   '-smp', str(a.smp), '-m', f'{a.memory_mib}M', '-nodefaults', '-display', 'none',
                   '-monitor', 'none', '-serial', 'stdio', '-nic', 'none', '-no-reboot',
                   '-kernel', str(guest_kernel), '-append', cmdline]
        for index, ((path, options), serial) in enumerate(zip(drives, SERIALS)):
            command += ['-drive', f'file={path},format=raw,if=none,id=d{index}' + (',' + options if options else ''),
                        '-device', f'virtio-blk-device,bus=virtio-mmio-bus.{index},drive=d{index},serial={serial}']
        result.update(guest_command=[portable(w, out) for w in command], guest_timeout_seconds=a.timeout)
        save()
        print(f'Installing the packages in a QEMU guest (budget {a.timeout} s); progress in {out}/console.log',
              flush=True)
        try:
            with (out / 'console.log').open('wb') as log:
                proc = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=a.timeout)
            result['guest_returncode'] = proc.returncode
        except subprocess.TimeoutExpired:
            result.update(guest_returncode=None, guest_timed_out=True)
        finally:
            inputs.unlink()
            guest_kernel.unlink()
        t = lap('guest', t)
        guest_dir = out / 'guest'
        with tarfile.open(result_disk) as tar:
            tar.extractall(guest_dir, filter='data')
        result_disk.unlink()
        log = (guest_dir / 'install.log').read_text(errors='replace')
        if 'PIANO_ROOTFS_GUEST_DONE' not in log or 'PIANO_ROOTFS_EXIT status=0' not in log:
            raise RuntimeError('The guest did not complete; see guest/install.log and console.log')
        (out / 'ubuntu-set').mkdir()
        for f in sorted((guest_dir / 'ubuntu-set').iterdir()):
            f.replace(out / 'ubuntu-set' / f.name)
        (guest_dir / 'ubuntu-set').rmdir()
        set_manifest = json.loads((out / 'ubuntu-set/manifest.json').read_text())
        if (set_manifest['kernel_release'] != release or set_manifest['root'] != f'PARTLABEL={ROOT_PARTLABEL}'
                or set_manifest['serial_in_cmdline'] or set_manifest['debug']
                or set_manifest['private_bt_address_injected'] or set_manifest['private_wlan_address_injected']):
            raise RuntimeError('The guest built a boot set that is not the address-free release set')
        set_hashes = {n + '.img': set_manifest['outputs'][n]['sha256'] for n in ('boot', 'init_boot', 'vendor_boot')}
        boot_hashes = {line.split()[1]: line.split()[0]
                       for line in (guest_dir / 'boot-files.sha256').read_text().splitlines()}
        result.update(boot_set={'cmdline': set_manifest['cmdline'], 'images_sha256': set_hashes,
                                'effective_dtb_sha256': set_manifest['effective_dtb_sha256'],
                                'manifest_sha256': sha(out / 'ubuntu-set/manifest.json')},
                      boot_files_sha256=boot_hashes)
        save()

        # Seal: whole-filesystem check, hashes, sparse image, offline checks.
        with (out / 'e2fsck.log').open('wb') as log:
            subprocess.run([str(a.e2fsck.resolve()), '-fn', str(image)], stdout=log, stderr=subprocess.STDOUT,
                           env=env, check=True)
        final = out / 'root.ext4'
        image.replace(final)
        t = lap('e2fsck', t)
        expected = {d['package']: d['version'] for _, d in debs}
        scratch = out / 'scratch'
        scratch.mkdir()
        report = verify(Debugfs(a.debugfs.resolve(), final, env), scratch, expected, release, caps,
                        set_hashes, boot_hashes)
        scratch.rmdir()
        (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
        if not report['passed']:
            raise RuntimeError(f'Offline checks failed: {report["failed"]}; see verification.json')
        t = lap('verify', t)
        subprocess.run(['img2simg', str(final), str(out / 'root.sparse.img')], check=True)
        t = lap('img2simg', t)
        outputs = {n: {'bytes': (out / n).stat().st_size, 'sha256': sha(out / n)}
                   for n in ('root.ext4', 'root.sparse.img')}
        outputs['root.ext4']['allocated_bytes'] = final.stat().st_blocks * 512
        (out / 'SHA256SUMS').write_text(''.join(f'{v["sha256"]}  {n}\n' for n, v in outputs.items()))
        t = lap('hash', t)
        result.update(state='ROOT_IMAGE_BUILT_OFFLINE_CHECKS_PASS_NOT_BOOTED', outputs=outputs,
                      verification_sha256=sha(out / 'verification.json'),
                      total_seconds=round(time.monotonic() - started, 1))
    except Exception as exc:
        result.update(state='FAILED', error=str(exc))
        save()
        raise
    save()
    print(json.dumps({k: result[k] for k in ('state', 'kernel_release', 'outputs')}, indent=2))


if __name__ == '__main__':
    main()
