# SPDX-License-Identifier: MIT
"""Shared, fail-closed slot-A helpers for piano-slot-success and piano-boot-switch.

One implementation of: the running-slot judgement, discovery of the UFS LUN
that holds boot_a/boot_b, GPT parsing and validation, boot-partition
location, boot image header classification, image-set checks and the lock.

GPT handling is adapted from liuqin-mark-slot-successful.c (MIT) in
https://github.com/yzddmr6/xiaomipad-6pro-mainline at
265b26fb268809167cfc45e3071e6956d735e1bb, device/boot/; see NOTICE.
Changes: Python; every location is read from the headers and checked instead
of pinned device geometry; the boot LUN is found by GPT names below the piano
UFS controller; a damaged backup copy is refused rather than rebuilt.

Qualcomm keeps the A/B state in bits 48-55 of each slot partition's GPT
attributes: b48-49 priority, b50 active, b51-53 retry count, b54 successful,
b55 unbootable.  Selecting a slot also swaps the type GUIDs of every _a/_b
pair and moves the UFS boot LUN, which only the bootloader does.  Nothing
here selects a slot; only slot A is accepted.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import struct
import subprocess
import syslog
import uuid
import zlib

# The internal UFS host is identified by its devicetree node and bound driver, not
# by device name: mainline names it 1d84000.ufs (node ufs@1d84000), while ABL's
# androidboot.bootdevice says 1d84000.ufshc.  On piano ufshcd-qcom binds only it.
UFS_COMPATIBLE = b'qcom,sm8750-ufshc'
UFS_DRIVER = 'ufshcd-qcom'
NAMES = ('init_boot', 'vendor_boot', 'boot')  # write order: the kernel last
IMAGES = tuple(n + '.img' for n in NAMES)
SETS = ('ubuntu', 'ubuntu.prev', 'android')
UBUNTU_SETS = ('ubuntu', 'ubuntu.prev')
UBUNTU_MARKER = 'piano.boot=persistent'
LOCK = '/run/piano-boot-switch.lock'
STORE = '/var/lib/piano/switch'
COMPATIBLE = b'xiaomi,piano'

ACTIVE = 1 << 50
SUCCESSFUL = 1 << 54
UNBOOTABLE = 1 << 55
SUCCESSFUL_BYTE, SUCCESSFUL_MASK = 54, 0x40  # entry byte 48 + 54 // 8, bit 54 % 8
GPT_REVISION = 0x00010000
ENTRY_SIZE = 128
MAX_ENTRY_BYTES = 1 << 20


class Refusal(Exception):
    """A precondition failed.  `code` is stable for scripts and tests."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Host:
    """File-system root and side effects.  Tests pass a temporary root."""

    def __init__(self, root='/'):
        self.root = Path(root)
        self.real = self.root == Path('/')
        self.events = []

    def path(self, name):
        return self.root / str(name).lstrip('/')

    def require_root(self):
        if self.real and os.geteuid() != 0:
            raise Refusal('not-root', 'Root is required')

    def is_device(self, path):
        """A block device on the real system; a regular file below a test root."""
        mode = os.stat(path).st_mode
        return stat.S_ISBLK(mode) if self.real else stat.S_ISREG(mode)

    def log(self, ident, message, error=False):
        if self.real:
            syslog.openlog(ident, syslog.LOG_PID)
            syslog.syslog(syslog.LOG_ERR if error else syslog.LOG_INFO, message)
        self.events.append(('log', ident, message))

    def run(self, argv, check=True):
        self.events.append(('run', list(argv)))
        if self.real:
            return subprocess.run(argv, check=check, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        return 0


def crc32(data):
    return zlib.crc32(data) & 0xffffffff


def pwrite_all(fd, data, offset):
    view = memoryview(data)
    while view:
        count = os.pwrite(fd, view, offset)
        if count <= 0:
            raise OSError('Short write')
        view, offset = view[count:], offset + count


def digest(path, size):
    """SHA-256 of exactly `size` bytes from the start of `path`."""
    h = hashlib.sha256()
    left = size
    with open(path, 'rb', buffering=0) as f:
        while left:
            chunk = f.read(min(left, 1 << 20))
            if not chunk:
                raise OSError(f'Short read from {path}')
            h.update(chunk)
            left -= len(chunk)
    return h.hexdigest()


def flags(attrs):
    return {'attributes': f'0x{attrs:016x}', 'priority': (attrs >> 48) & 3,
            'active': bool(attrs & ACTIVE), 'retry': (attrs >> 51) & 7,
            'successful': bool(attrs & SUCCESSFUL), 'unbootable': bool(attrs & UNBOOTABLE)}


# --- kernel command line ----------------------------------------------------

def kernel_words(host):
    return host.path('/proc/cmdline').read_text().split()


def require_piano(host):
    path = host.path('/sys/firmware/devicetree/base/compatible')
    if not path.exists() or COMPATIBLE not in path.read_bytes().split(b'\0'):
        raise Refusal('not-piano', 'The devicetree does not identify a Xiaomi Pad 8 Pro (xiaomi,piano)')


def slot_suffix(host):
    """'_a'/'_b' from /proc/bootconfig or /proc/cmdline; None when neither has it."""
    found = set()
    for word in kernel_words(host):
        for key in ('androidboot.slot_suffix=', 'slot_suffix='):
            if word.startswith(key):
                found.add(word[len(key):])
    bootconfig = host.path('/proc/bootconfig')
    if bootconfig.exists():
        for match in re.finditer(r'^\s*(?:androidboot\.)?slot_suffix\s*=\s*"?([^"\s]*)"?\s*$',
                                 bootconfig.read_text(), re.M):
            found.add(match[1])
    if not found:
        return None
    if len(found) != 1 or not found <= {'_a', '_b'}:
        raise Refusal('slot-suffix-conflict', f'Conflicting or invalid slot suffixes: {sorted(found)}')
    return found.pop()


# --- GPT ----------------------------------------------------------------------

class Entry:
    def __init__(self, index, raw):
        self.index, self.number = index, index + 1
        self.type_guid = str(uuid.UUID(bytes_le=raw[:16]))
        self.unique_guid = str(uuid.UUID(bytes_le=raw[16:32]))
        self.first, self.last, self.attrs = struct.unpack_from('<QQQ', raw, 32)
        self.name = raw[56:128].decode('utf-16-le', 'replace').split('\0')[0]


class Copy:
    """One GPT header block and its entry array, as read."""

    def __init__(self, lba, block, entries_lba, entries):
        self.lba, self.block, self.entries_lba, self.entries = lba, block, entries_lba, entries
        (self.revision, self.header_size, self.header_crc, self.reserved, self.my_lba,
         self.alternate_lba, self.first_usable, self.last_usable) = struct.unpack_from('<IIIIQQQQ', block, 8)
        self.disk_guid = str(uuid.UUID(bytes_le=block[56:72]))
        _, self.count, self.entry_size, self.entries_crc = struct.unpack_from('<QIII', block, 72)


def read_copy(f, lba, lbs, which):
    f.seek(lba * lbs)
    block = f.read(lbs)
    if len(block) != lbs:
        raise Refusal('gpt-short-read', f'{which} GPT header could not be read')
    if block[:8] != b'EFI PART':
        raise Refusal('gpt-signature', f'{which} GPT header has no EFI PART signature')
    revision, header_size, header_crc = struct.unpack_from('<III', block, 8)
    if revision != GPT_REVISION:
        raise Refusal('gpt-revision', f'{which} GPT revision is 0x{revision:08x}')
    if not 92 <= header_size <= lbs:
        raise Refusal('gpt-header-size', f'{which} GPT header size {header_size} is invalid')
    check = bytearray(block[:header_size])
    check[16:20] = bytes(4)
    if crc32(check) != header_crc:
        raise Refusal('gpt-header-crc', f'{which} GPT header CRC32 mismatch')
    entries_lba, count, entry_size = struct.unpack_from('<QII', block, 72)
    if entry_size != ENTRY_SIZE or not 1 <= count or count * entry_size > MAX_ENTRY_BYTES:
        raise Refusal('gpt-entry-geometry', f'{which} GPT entry geometry {count}x{entry_size} is unsupported')
    f.seek(entries_lba * lbs)
    entries = f.read(count * entry_size)
    if len(entries) != count * entry_size:
        raise Refusal('gpt-short-read', f'{which} GPT entry array could not be read')
    copy = Copy(lba, block, entries_lba, entries)
    if copy.reserved:
        raise Refusal('gpt-reserved', f'{which} GPT header reserved field is not zero')
    if crc32(entries) != copy.entries_crc:
        raise Refusal('gpt-entries-crc', f'{which} GPT entry array CRC32 mismatch')
    return copy


def entry_blocks(copy, lbs):
    return -(-copy.count * copy.entry_size // lbs)


def check_location(copy, primary, disk_lbas, lbs):
    which = 'Primary' if primary else 'Backup'
    last_lba = disk_lbas - 1
    want_my, want_alt = (1, last_lba) if primary else (last_lba, 1)
    if copy.my_lba != want_my or copy.alternate_lba != want_alt:
        raise Refusal('gpt-lba-links', f'{which} GPT my/alternate LBA {copy.my_lba}/{copy.alternate_lba} '
                      f'does not cross-link LBA 1 and {last_lba}')
    if not 2 <= copy.first_usable <= copy.last_usable < last_lba:
        raise Refusal('gpt-usable-range', f'{which} GPT usable range is invalid')
    end = copy.entries_lba + entry_blocks(copy, lbs)
    if primary:
        inside = copy.entries_lba >= 2 and end <= copy.first_usable
    else:
        inside = copy.entries_lba > copy.last_usable and end <= last_lba
    if not inside:
        raise Refusal('gpt-entries-location', f'{which} GPT entry array at LBA {copy.entries_lba} '
                      'overlaps a header or the usable area')


def table(copy):
    rows = []
    for index in range(copy.count):
        raw = copy.entries[index * copy.entry_size:(index + 1) * copy.entry_size]
        if raw[:16] != bytes(16):
            rows.append(Entry(index, raw))
    return rows


def unique(rows, name):
    hits = [r for r in rows if r.name == name]
    if not hits:
        raise Refusal('name-missing', f'GPT has no {name} entry')
    if len(hits) > 1:
        raise Refusal('name-duplicate', f'GPT has {len(hits)} entries named {name}')
    return hits[0]


class Disk:
    """A validated whole-disk GPT of one UFS LUN."""

    def __init__(self, host, name, strict):
        self.host, self.name = host, name
        self.sys = host.path('/sys/block') / name
        real = self.sys.resolve()
        self.scsi = real.parent.parent.name
        self.lbs = int((self.sys / 'queue/logical_block_size').read_text())
        size = int((self.sys / 'size').read_text()) * 512
        if self.lbs not in (512, 4096) or size % self.lbs:
            raise Refusal('disk-geometry', f'{name}: unsupported logical block size {self.lbs}')
        self.disk_lbas = size // self.lbs
        self.node = host.path('/dev') / name
        if not host.is_device(self.node):
            raise Refusal('not-block-device', f'{self.node} is not a block device')
        self.read_only = (self.sys / 'ro').read_text().strip() != '0'
        self.backup_error = None
        with open(self.node, 'rb', buffering=0) as f:
            try:
                self.primary = read_copy(f, 1, self.lbs, 'Primary')
                check_location(self.primary, True, self.disk_lbas, self.lbs)
            except Refusal as error:
                raise Refusal(error.code, f'{name}: {error}') from None
            self.rows = table(self.primary)
            try:
                self.backup = read_copy(f, self.disk_lbas - 1, self.lbs, 'Backup')
                check_location(self.backup, False, self.disk_lbas, self.lbs)
                p, b = self.primary, self.backup
                if (p.disk_guid, p.first_usable, p.last_usable, p.count, p.entry_size) != \
                        (b.disk_guid, b.first_usable, b.last_usable, b.count, b.entry_size):
                    raise Refusal('gpt-header-fields-differ', 'Primary and backup GPT headers describe different disks')
                if p.entries != b.entries:
                    raise Refusal('gpt-copies-differ', 'Primary and backup GPT entry arrays are not identical')
            except Refusal as error:
                if strict:
                    raise Refusal(error.code, f'{name}: {error}') from None
                self.backup, self.backup_error = None, {'code': error.code, 'message': str(error)}

    def entry(self, name):
        return unique(self.rows, name)

    def partition(self, name):
        """Kernel node of a GPT entry, checked against sysfs geometry."""
        entry = self.entry(name)
        sys = self.sys / f'{self.name}{entry.number}'
        if not sys.is_dir() or int((sys / 'partition').read_text()) != entry.number:
            raise Refusal('partition-node', f'{name}: kernel partition {self.name}{entry.number} is missing')
        start, size = int((sys / 'start').read_text()) * 512, int((sys / 'size').read_text()) * 512
        if start != entry.first * self.lbs or size != (entry.last - entry.first + 1) * self.lbs:
            raise Refusal('partition-geometry', f'{name}: kernel and on-disk GPT geometry disagree')
        node = self.host.path('/dev') / f'{self.name}{entry.number}'
        if not self.host.is_device(node):
            raise Refusal('not-block-device', f'{node} is not a block device')
        return Partition(name, entry, node, start, size, (sys / 'dev').read_text().strip())

    def report(self):
        return {'controller': getattr(self, 'controller', None), 'disk': self.name, 'scsi': self.scsi,
                'logical_block_size': self.lbs,
                'disk_guid': self.primary.disk_guid,
                'backup_gpt': 'valid' if self.backup else self.backup_error}


class Partition:
    def __init__(self, name, entry, node, start, size, dev):
        self.name, self.entry, self.node, self.start, self.size, self.dev = name, entry, node, start, size, dev


def ufs_controller(host):
    """The one platform device with a qcom,sm8750-ufshc devicetree node, bound to ufshcd-qcom."""
    hits = []
    for dev in sorted(host.path('/sys/bus/platform/devices').iterdir()):
        compatible = dev / 'of_node/compatible'
        if compatible.is_file() and UFS_COMPATIBLE in compatible.read_bytes().split(b'\0'):
            hits.append(dev)
    if len(hits) != 1:
        raise Refusal('ufs-controller-missing' if not hits else 'ufs-controller-ambiguous',
                      f'Expected one platform device compatible with {UFS_COMPATIBLE.decode()}, '
                      f'found {[d.name for d in hits]}')
    driver = hits[0] / 'driver'
    if not driver.exists() or driver.resolve().name != UFS_DRIVER:
        raise Refusal('ufs-controller-unbound', f'{hits[0].name} is not bound to {UFS_DRIVER}')
    return hits[0].resolve()


def ufs_disks(host):
    """(controller, whole-disk names) of the sd* disks below the internal UFS host."""
    controller = ufs_controller(host)
    names = [d.name for d in sorted(host.path('/sys/block').glob('sd*'))
             if d.resolve().is_relative_to(controller)]
    return controller, names


def boot_disk(host, strict):
    """The single UFS LUN whose GPT holds boot_a and boot_b; never by sdX name."""
    hits = []
    controller, names = ufs_disks(host)
    for name in names:
        disk = Disk(host, name, strict=False)
        labels = [r.name for r in disk.rows]
        if 'boot_a' in labels or 'boot_b' in labels:
            hits.append(name)
    if not hits:
        raise Refusal('boot-lun-missing', f'No LUN below {controller.name} has boot_a/boot_b')
    if len(hits) > 1:
        raise Refusal('boot-lun-ambiguous', f'boot_a/boot_b appear on several LUNs: {hits}')
    disk = Disk(host, hits[0], strict)
    disk.controller = controller.name
    disk.entry('boot_a')
    disk.entry('boot_b')
    return disk


def slot_state(host, disk):
    """Slot A must be the slot ABL chose; refuses otherwise.  Never selects a slot."""
    suffix = slot_suffix(host)
    if suffix not in (None, '_a'):
        raise Refusal('not-slot-a', f'Running from slot {suffix}; only slot A is supported')
    a, b = flags(disk.entry('boot_a').attrs), flags(disk.entry('boot_b').attrs)
    state = {'slot': 'a', 'source': 'gpt' if suffix is None else 'bootargs+gpt', 'boot_a': a, 'boot_b': b}
    if not a['active'] or a['priority'] != 3 or b['active']:
        raise Refusal('slot-a-not-selected', 'GPT does not show slot A as the only active slot with priority 3')
    if a['unbootable']:
        raise Refusal('slot-a-unbootable', 'boot_a is marked unbootable')
    return state


# --- boot images ----------------------------------------------------------------

def _cstr(raw):
    return raw.split(b'\0', 1)[0].decode('ascii', 'replace')


def header_cmdline(head):
    """Command line stored in a boot or vendor_boot header; None if neither."""
    if head[:8] == b'ANDROID!':
        if struct.unpack_from('<I', head, 40)[0] >= 3:
            return _cstr(head[44:44 + 1536])
        return _cstr(head[64:64 + 512]) + _cstr(head[608:608 + 1024])
    if head[:8] == b'VNDRBOOT':
        return _cstr(head[28:28 + 2048])
    return None


def read_head(path):
    with open(path, 'rb', buffering=0) as f:
        return f.read(4096)


def heads_kind(heads):
    """'ubuntu' when the piano persistent marker is in boot/vendor_boot, else 'android',
    or None when the three images are not boot/init_boot/vendor_boot headers."""
    if heads['boot'][:8] != b'ANDROID!' or heads['init_boot'][:8] != b'ANDROID!' or \
            heads['vendor_boot'][:8] != b'VNDRBOOT':
        return None
    words = (header_cmdline(heads['boot']) + ' ' + header_cmdline(heads['vendor_boot'])).split()
    return 'ubuntu' if UBUNTU_MARKER in words else 'android'


def booted_from_slot(host, heads):
    """This boot used the slot's command line: no fastboot-booted image vouches for the slot."""
    words = kernel_words(host)
    joined = ' ' + ' '.join(words) + ' '
    boot = (header_cmdline(heads['boot']) or '').split()
    vendor = (header_cmdline(heads['vendor_boot']) or '').split()
    if not boot:
        raise Refusal('slot-cmdline-empty', 'boot_a carries no command line')
    for part in (boot, vendor):
        if part and ' ' + ' '.join(part) + ' ' not in joined:
            raise Refusal('not-booted-from-slot', 'The running command line does not contain the boot_a command line')
    extra = [w for w in words if w.startswith('piano.') and w not in boot + vendor]
    if extra:
        raise Refusal('not-booted-from-slot', f'Running with {" ".join(extra)}, absent from boot_a: '
                      'this boot did not come from the slot image')


# --- image sets ---------------------------------------------------------------

def store(host):
    return host.path(STORE)


def read_sums(directory):
    path = directory / 'SHA256SUMS'
    if not path.is_file():
        raise Refusal('set-missing', f'{directory} has no SHA256SUMS')
    sums = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 2:
            raise Refusal('set-sums-invalid', f'{path}: malformed line')
        sha, name = parts[0], parts[1].lstrip('*')
        if name in IMAGES:
            if name in sums or not re.fullmatch('[0-9a-f]{64}', sha):
                raise Refusal('set-sums-invalid', f'{path}: duplicate or invalid digest for {name}')
            sums[name] = sha
    if set(sums) != set(IMAGES):
        raise Refusal('set-sums-invalid', f'{path} does not list all of {", ".join(IMAGES)}')
    return sums


def known_sums(host):
    """SHA256SUMS of every present store set; malformed sets are reported, not trusted."""
    result, errors = {}, {}
    for name in SETS:
        directory = store(host) / name
        if directory.is_dir():
            try:
                result[name] = read_sums(directory)
            except Refusal as error:
                errors[name] = str(error)
    return result, errors


def occupant(slot_hashes, sums):
    for name in SETS:
        if sums.get(name) == slot_hashes:
            return name
    return None


def check_set(host, name, parts, kind):
    """Full check of a store set: digests, sizes == partition sizes, header kind."""
    directory = store(host) / name
    sums = read_sums(directory)
    heads = {}
    for n in NAMES:
        image = directory / (n + '.img')
        if not image.is_file():
            raise Refusal('set-missing', f'{image} is missing')
        if image.stat().st_size != parts[n].size:
            raise Refusal('set-size', f'{image} is {image.stat().st_size} B, partition is {parts[n].size} B')
        if digest(image, parts[n].size) != sums[n + '.img']:
            raise Refusal('set-digest', f'{image} does not match SHA256SUMS')
        heads[n] = read_head(image)
    found = heads_kind(heads)
    if found != kind:
        raise Refusal('set-kind', f'{directory} holds {found or "non-boot"} images, expected {kind}')
    return sums


def slot_hashes(parts):
    return {n + '.img': digest(parts[n].node, parts[n].size) for n in NAMES}


def slot_heads(parts):
    return {n: read_head(parts[n].node) for n in NAMES}


# --- locking and critical sections -------------------------------------------

@contextlib.contextmanager
def slot_lock(host):
    """Device lock shared by the marker and the switch, then the store lock that
    piano-boot-update holds while it rotates image sets."""
    with open(host.path(LOCK), 'a') as device:
        try:
            fcntl.flock(device, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refusal('locked', 'Another piano boot-slot operation is running') from None
        if not store(host).is_dir():
            yield
            return
        with open(store(host) / '.lock', 'a') as stored:
            fcntl.flock(stored, fcntl.LOCK_EX)
            yield


CRITICAL_SIGNALS = {signal.SIGHUP, signal.SIGINT, signal.SIGTERM, signal.SIGQUIT}


@contextlib.contextmanager
def signals_blocked():
    """Blocked, not ignored: a pending stop request takes effect after the section."""
    old = signal.pthread_sigmask(signal.SIG_BLOCK, CRITICAL_SIGNALS)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def write_json(path, data):
    tmp = path.with_name('.' + path.name + '.tmp')
    with open(tmp, 'w') as f:
        f.write(json.dumps(data, indent=2, sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
