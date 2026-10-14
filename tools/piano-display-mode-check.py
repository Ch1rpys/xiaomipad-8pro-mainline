#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Device-side GNOME/DSI mode and DPMS acceptance (root, invoked over SSH).

Python standard library, busctl/loginctl and GNOME's existing libgio/glib.
No package/service/driver changes or persistent monitor configuration. The only
kernel write is selecting a DRM debugfs CRC source; data is opened read-only.
Reports contain private device/session information: keep --output private.

A moving pointer must change the layer-mixer CRC on BOTH bonded display halves.
CRC is measured before DSI/panel output; PASS is the specified digital-path
acceptance, not proof of panel light output. Run in a fresh recoverable RAM boot:
a D-state DRM call cannot be cancelled by this program's userspace deadlines.

Protocol: Mutter 50.1 DisplayConfig/RemoteDesktop XML; DRM drm_debugfs_crc.c.
The input session lifetime follows piano-desktop-drive.py: its creator must
keep the SAME D-Bus connection for Start/Notify*/Stop. Separate gdbus processes
cannot do that. A short-lived unprivileged ctypes/GIO worker owns that session.
"""
import argparse
import ctypes
import errno
import fcntl
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import pwd
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time

DC = 'org.gnome.Mutter.DisplayConfig'
DC_PATH = '/org/gnome/Mutter/DisplayConfig'
RD = 'org.gnome.Mutter.RemoteDesktop'
RATES = (60, 90, 120, 144)
APPLY_SIGNATURE = 'uua(iiduba(ssa{sv}))a{sv}'
BAD_LOG = re.compile(
    r'dsi_err_worker|dsi.*fifo|underrun|underflow|\bWARNING\b|Call trace|'
    r'Overflow of CRC buffer|'
    r'(?:frame|vblank|vsync|pp_done).*?time(?:d[ _-]*out|out)|'
    r'(?:smmu|iommu).*?(?:fault|translation.*(?:fail|error))|'
    r'(?:pll|clock|clk|rcg).*?(?:stuck|time(?:d out|out)|fail|error|'
    r"didn.t update|already (?:disabled|unprepared))", re.I)


class Unsupported(RuntimeError):
    pass


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def unwrap(value):
    """busctl --json=short variants are {type: signature, data: value}."""
    if isinstance(value, dict):
        if set(value) == {'type', 'data'}:
            return unwrap(value['data'])
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v) for v in value]
    return value


def parse_state(reply):
    serial, monitors, logical, properties = unwrap(reply)
    selected = [m for m in monitors if m[0][0] == 'DSI-1']
    # Relative pointer motion has an unambiguous viewport with just this panel.
    # Reject other layouts rather than disabling outputs or moving across them.
    if len(selected) != 1 or len(monitors) != 1 or len(logical) != 1:
        raise Unsupported('requires exactly one connected/active DSI-1 monitor')
    monitor = selected[0]
    group = logical[0]
    if len(group[5]) != 1 or group[5][0] != monitor[0]:
        raise Unsupported('DSI-1 is not the sole logical monitor')
    modes = []
    for ident, width, height, hz, preferred_scale, scales, props in monitor[1]:
        if not math.isfinite(hz) or hz <= 0:
            raise ValueError('invalid refresh rate in Mutter reply')
        modes.append(dict(id=ident, width=width, height=height, hz=hz,
                          scales=scales, properties=props))
    current = [m for m in modes if m['properties'].get('is-current', False)]
    if len(current) != 1:
        raise Unsupported('Mutter must identify exactly one current DSI-1 mode')
    scale = group[2]
    if not math.isfinite(scale) or scale <= 0 or group[3] not in range(8):
        raise ValueError('invalid logical monitor scale/transform')
    if properties.get('layout-mode') not in (1, 2):
        raise Unsupported('unknown Mutter layout-mode')
    return dict(serial=serial, spec=monitor[0], modes=modes, current=current[0],
                x=group[0], y=group[1], scale=scale, transform=group[3], primary=group[4],
                monitor_properties=monitor[2], properties=properties)


def choose_modes(state):
    selected = {}
    current = state['current']
    for rate in RATES:
        candidates = [m for m in state['modes']
                      if (m['width'], m['height']) == (current['width'], current['height'])
                      and abs(m['hz'] - rate) <= 0.5
                      and not m['properties'].get('is-interlaced', False)
                      and m['properties'].get('refresh-rate-mode', 'fixed') == 'fixed'
                      and any(abs(s - state['scale']) < 1e-6 for s in m['scales'])]
        if len(candidates) != 1:
            raise Unsupported(f'{rate} Hz: expected one fixed mode at original size/scale, got {len(candidates)}')
        selected[rate] = candidates[0]
    if current['properties'].get('refresh-rate-mode', 'fixed') != 'fixed':
        raise Unsupported('original mode uses variable refresh rate')
    return selected


def apply_arguments(original, fresh_serial, mode_id):
    """Typed busctl arguments, method=1 (temporary), preserving layout/colour."""
    args = [str(fresh_serial), '1', '1', str(original['x']), str(original['y']),
            str(original['scale']), str(original['transform']),
            str(original['primary']).lower(), '1', 'DSI-1', mode_id]
    props = original['monitor_properties']
    settings = []
    if 'is-underscanning' in props:
        settings += ['underscanning', 'b', str(props['is-underscanning']).lower()]
    if 'color-mode' in props:
        settings += ['color-mode', 'u', str(props['color-mode'])]
    args += [str(len(settings) // 3), *settings]
    if original['properties'].get('supports-changing-layout-mode', False):
        args += ['1', 'layout-mode', 'u', str(original['properties']['layout-mode'])]
    else:
        args += ['0']
    return args


def mode_matches(state, original, mode):
    return (state['current']['id'] == mode['id'] and state['spec'] == original['spec']
            and all(state[key] == original[key] for key in ('x', 'y', 'scale', 'transform', 'primary'))
            and state['properties']['layout-mode'] == original['properties']['layout-mode'])


def parse_crc_line(line):
    fields = line.split()
    if len(fields) < 2:
        raise ValueError(f'incomplete CRC line: {line!r}')
    if fields[0] == 'XXXXXXXXXX':
        raise Unsupported('CRC source has no valid frame counter')
    if any(not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{1,8}', x) for x in fields):
        raise ValueError(f'invalid CRC fields: {line!r}')
    return int(fields[0], 16), tuple(int(x, 16) for x in fields[1:])


def crc_metrics(samples, expected_hz):
    """Samples: {time: host monotonic seconds, frame: uint32, values: [CRC]}.

    Rate uses FRAME delta, not line count. Gaps in CRC delivery are recorded;
    counter wrap is allowed, duplicate/backward/reset counters are rejected.
    """
    result = {'status': 'FAIL', 'samples': len(samples), 'expected_hz': expected_hz,
              'fps': None, 'unique_crc': 0, 'unique_per_lm': []}
    if len(samples) < 2:
        result['reason'] = 'no advancing CRC stream'
        return result
    channels = {len(s['values']) for s in samples}
    if channels != {2}:
        return dict(result, status='INCOMPLETE', reason='bonded DSI requires two LM CRC columns')
    elapsed = samples[-1]['time'] - samples[0]['time']
    if elapsed < 0.5:
        return dict(result, status='INCOMPLETE', reason='insufficient timed CRC span')
    deltas = [(b['frame'] - a['frame']) & 0xffffffff for a, b in zip(samples, samples[1:])]
    if any(d == 0 or d >= 0x80000000 for d in deltas):
        return dict(result, reason='duplicate, backwards or reset frame counter')
    frames = sum(deltas)
    unique = len({tuple(s['values']) for s in samples})
    per_lm = [len({s['values'][i] for s in samples}) for i in range(2)]
    fps = frames / elapsed
    result.update(seconds=elapsed, frames=frames, fps=fps, unique_crc=unique,
                  unique_per_lm=per_lm, max_frame_gap=max(deltas),
                  rate_ok=abs(fps - expected_hz) <= 0.15 * expected_hz + 1e-9,
                  content_ok=unique >= 2 and all(n >= 2 for n in per_lm))
    result['status'] = 'PASS' if result['rate_ok'] and result['content_ok'] else 'FAIL'
    return result


def filter_kernel(lines):
    return [line for line in lines if BAD_LOG.search(line)]


def active_crtc(state_text):
    blocks = re.split(r'(?=^(?:plane|crtc|connector)\[\d+\]:)', state_text, flags=re.M)
    connector = [b for b in blocks if re.match(r'connector\[\d+\]: DSI-1\s*\n', b)]
    if len(connector) != 1:
        raise Unsupported('cannot resolve DSI-1 in DRM atomic state')
    match = re.search(r'^\s+crtc=(crtc-\d+)\s*$', connector[0], re.M)
    if not match:
        raise Unsupported('DSI-1 has no mapped CRTC')
    name = match[1]
    crtc = [b for b in blocks if re.match(r'crtc\[\d+\]: ' + re.escape(name) + r'\s*\n', b)]
    if len(crtc) != 1 or not re.search(r'^\s+active=1\s*$', crtc[0], re.M):
        raise RuntimeError('DRM DSI CRTC is not active')
    return name


def discover_crc():
    connectors = [p for p in Path('/sys/class/drm').glob('card*-DSI-1')
                  if re.fullmatch(r'card\d+-DSI-1', p.name)
                  and (p / 'status').read_text().strip() == 'connected']
    if len(connectors) != 1:
        raise Unsupported('expected one connected DRM DSI-1')
    card = connectors[0].name.rsplit('-DSI-1', 1)[0]
    device = Path('/sys/class/drm') / card
    if (device / 'device/driver').resolve().name != 'msm_dpu':
        raise Unsupported('DSI-1 is not driven by msm_dpu')
    minor = int((device / 'dev').read_text().strip().split(':')[1])
    debug = Path('/sys/kernel/debug/dri') / str(minor)
    if not (debug / 'state').is_file():
        raise Unsupported('DRM debugfs state is unavailable (not mounted or not configured)')
    crtc = active_crtc((debug / 'state').read_text())
    path = debug / crtc / 'crc'
    if not (path / 'control').is_file() or not (path / 'data').is_file():
        raise Unsupported(f'DRM CRC interface unavailable: {path}')
    return path


class KernelLog:
    def __init__(self):
        self.fd = os.open('/dev/kmsg', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        os.lseek(self.fd, 0, os.SEEK_END)  # no clearing and no historical failures
        self.entries = []
        self.errors = []
        self.last_seq = None

    def drain(self):
        for _ in range(16384):
            try:
                raw = os.read(self.fd, 65536).decode('utf-8', 'replace')
            except BlockingIOError:
                return
            except OSError as error:
                if error.errno == errno.EPIPE:
                    self.errors.append('kernel ring overwritten: log interval incomplete')
                    continue
                raise
            if not raw:
                raise RuntimeError('unexpected /dev/kmsg EOF')
            meta, text = raw.split(';', 1)
            fields = meta.split(',')
            seq = int(fields[1])
            if self.last_seq is not None and seq != self.last_seq + 1:
                self.errors.append(f'kernel sequence gap {self.last_seq}->{seq}')
            self.last_seq = seq
            self.entries.append({'seq': seq, 'uptime_us': int(fields[2]), 'message': text.rstrip()})
        self.errors.append('kernel log flood exceeded bounded read budget')

    def close(self):
        os.close(self.fd)


class CRC:
    def __init__(self, path, source):
        self.path, self.source = path, source
        self.fd = None
        self.samples, self.errors = [], []
        self.done = threading.Event()
        self.thread = None
        self.previous = None

    def __enter__(self):
        # DPU lacks get_crc_sources, so control can be empty. Its supported
        # source is selected explicitly. Opening data enables MISR; close stops it.
        control = (self.path / 'control').read_text().splitlines()
        selected = [line[:-1] for line in control if line.endswith('*')]
        self.previous = selected[0] if len(selected) == 1 else 'none'
        try:
            (self.path / 'control').write_text(self.source + '\n')
            self.fd = os.open(self.path / 'data', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError as error:
            # Do not change control again if another reader owns this CRTC.
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            try:
                (self.path / 'control').write_text(self.previous + '\n')
            except OSError as restore_error:
                raise RuntimeError(f'CRC open: {error}; control restore: {restore_error}') from error
            if error.errno in (errno.EOPNOTSUPP, errno.ENOSYS):
                raise Unsupported(f'CRC source unavailable: {error}') from error
            raise
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()
        return self

    def read(self):
        try:
            while not self.done.is_set():
                if not select.select([self.fd], [], [], 0.05)[0]:
                    continue
                while not self.done.is_set():
                    try:
                        raw = os.read(self.fd, 4096)
                    except BlockingIOError:
                        break
                    if not raw:
                        raise RuntimeError('CRC EOF during active sampling')
                    now = time.monotonic()
                    for line in raw.decode('ascii').splitlines():
                        frame, values = parse_crc_line(line)
                        self.samples.append({'time': now, 'frame': frame, 'values': values})
        except Exception as error:
            self.errors.append({'type': type(error).__name__, 'message': str(error)})

    def __exit__(self, *exc):
        self.done.set()
        try:
            self.thread.join(timeout=1)
            if self.thread.is_alive():
                raise RuntimeError('CRC reader did not stop; kernel call may be blocked')
        finally:
            try:
                os.close(self.fd)  # disables MISR before any subsequent modeset/DPMS
            finally:
                self.fd = None
                (self.path / 'control').write_text(self.previous + '\n')


class Pointer:
    def __init__(self, user, env):
        # A persistent unprivileged connection is mandatory for RemoteDesktop.
        # The root-owned script/output may be below /root: send just this one
        # function to the child, without making private directories world-readable.
        source = ('import ctypes, json, math, os, sys\n' + inspect.getsource(pointer_worker) +
                  '\ntry:\n    pointer_worker()\nexcept Exception as error:\n'
                  '    print(json.dumps({"ok": False, "error": str(error)}), flush=True)\n'
                  '    print(str(error), file=sys.stderr)\n    sys.exit(1)\n')
        self.proc = subprocess.Popen([sys.executable, '-c', source],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, cwd='/', env=env, user=user.pw_uid,
                                     group=user.pw_gid, extra_groups=os.getgrouplist(user.pw_name, user.pw_gid))
        try:
            self.reply()
        except Exception:
            self.close()
            raise

    def reply(self):
        if not select.select([self.proc.stdout], [], [], 7)[0]:
            raise TimeoutError('RemoteDesktop worker did not reply')
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError('RemoteDesktop worker exited: ' + self.proc.stderr.read().decode(errors='replace'))
        data = json.loads(line)
        if not data.get('ok'):
            raise RuntimeError('RemoteDesktop: ' + data.get('error', 'unknown error'))
        return data

    def move(self, dx, dy):
        self.proc.stdin.write((json.dumps({'move': [dx, dy]}) + '\n').encode())
        self.proc.stdin.flush()
        self.reply()

    def close(self):
        try:
            try:
                self.proc.stdin.close()  # EOF -> Stop on the same connection
            except BrokenPipeError:
                pass
            self.proc.wait(timeout=7)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2)
            raise RuntimeError('RemoteDesktop Stop timeout; disconnected worker')
        if self.proc.returncode:
            raise RuntimeError('RemoteDesktop cleanup failed: ' + self.proc.stderr.read().decode(errors='replace'))


def pointer_worker():
    """Only fixed RemoteDesktop calls, using GIO's existing session connection."""
    if os.geteuid() == 0:
        raise RuntimeError('pointer worker must be the desktop user')
    gio = ctypes.CDLL('libgio-2.0.so.0')
    glib = ctypes.CDLL('libglib-2.0.so.0')
    obj = ctypes.CDLL('libgobject-2.0.so.0')
    ptr, char, integer = ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
    class GError(ctypes.Structure):
        _fields_ = [('domain', ctypes.c_uint), ('code', integer), ('message', char)]
    def bind(lib, name, result, args):
        fn = getattr(lib, name); fn.restype = result; fn.argtypes = args; return fn
    bus_get = bind(gio, 'g_bus_get_sync', ptr, [integer, ptr, ctypes.POINTER(ptr)])
    call_sync = bind(gio, 'g_dbus_connection_call_sync', ptr,
                     [ptr, char, char, char, char, ptr, ptr, integer, integer, ptr, ctypes.POINTER(ptr)])
    parse = bind(glib, 'g_variant_parse', ptr, [ptr, char, ptr, ptr, ctypes.POINTER(ptr)])
    child = bind(glib, 'g_variant_get_child_value', ptr, [ptr, ctypes.c_size_t])
    string = bind(glib, 'g_variant_get_string', char, [ptr, ptr])
    sink = bind(glib, 'g_variant_ref_sink', ptr, [ptr])
    unref = bind(glib, 'g_variant_unref', None, [ptr])
    error_free = bind(glib, 'g_error_free', None, [ptr])
    object_unref = bind(obj, 'g_object_unref', None, [ptr])
    def checked(value, error):
        if value:
            return value
        message = ctypes.cast(error, ctypes.POINTER(GError)).contents.message.decode() if error else 'GIO failed'
        if error:
            error_free(error)
        raise RuntimeError(message)
    error = ptr()
    connection = checked(bus_get(2, None, ctypes.byref(error)), error)
    session = None
    def call(path, iface, method, params=None, want_path=False):
        error = ptr(); variant = None
        if params is not None:
            variant = checked(parse(None, params.encode(), None, None, ctypes.byref(error)), error)
            sink(variant)
        try:
            response = checked(call_sync(connection, RD.encode(), path.encode(), iface.encode(),
                                          method.encode(), variant, None, 1, 5000, None,
                                          ctypes.byref(error)), error)  # NO_AUTO_START
        finally:
            if variant:
                unref(variant)
        try:
            if want_path:
                value = child(response, 0)
                try:
                    return string(value, None).decode()
                finally:
                    unref(value)
        finally:
            unref(response)
    try:
        session = call('/org/gnome/Mutter/RemoteDesktop', RD, 'CreateSession', want_path=True)
        call(session, RD + '.Session', 'Start')
        print(json.dumps({'ok': True}), flush=True)
        for line in sys.stdin:
            try:
                dx, dy = json.loads(line)['move']
                if not all(math.isfinite(v) for v in (dx, dy)):
                    raise ValueError('non-finite pointer delta')
                call(session, RD + '.Session', 'NotifyPointerMotionRelative', f'({float(dx)}, {float(dy)})')
                print(json.dumps({'ok': True}), flush=True)
            except Exception as error:
                print(json.dumps({'ok': False, 'error': str(error)}), flush=True)
    finally:
        try:
            if session:
                call(session, RD + '.Session', 'Stop')
        finally:
            object_unref(connection)


class Check:
    def __init__(self, args):
        self.a = args
        self.out = args.output.resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        os.chmod(self.out, 0o700)
        shutil.copyfile(__file__, self.out / 'runner.py')
        self.result = {'schema': 1, 'status': 'INCOMPLETE', 'label': args.label,
                       'kernel': os.uname().release, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                       'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'criteria': {'fps_tolerance': 0.15, 'minimum_unique_crc': 2,
                                    'minimum_unique_per_lm': 2, 'sample_seconds': args.sample_seconds,
                                    'settle_seconds': args.settle_seconds, 'source': args.crc_source},
                       'steps': [], 'restore': {}, 'errors': []}
        self.user = self.env = self.original = self.pointer = self.log = None
        self.lock = None
        self.changed = False

    def command(self, argv, user=False):
        with (self.out / 'commands.jsonl').open('a') as f:
            f.write(json.dumps({'monotonic': time.monotonic(), 'argv': argv}) + '\n')
        opts = dict(env=self.env, user=self.user.pw_uid, group=self.user.pw_gid,
                    extra_groups=os.getgrouplist(self.user.pw_name, self.user.pw_gid)) if user else {}
        r = subprocess.run(argv, capture_output=True, text=True, timeout=7, **opts)
        if r.returncode:
            raise RuntimeError(f'{argv[0]}: {r.stderr.strip() or r.stdout.strip()}')
        return r.stdout

    def bus(self, method, signature=None, args=(), dest=DC, path=DC_PATH, iface=DC):
        cmd = ['busctl', '--user', '--json=short', '--no-pager', '--auto-start=no',
               '--allow-interactive-authorization=no', '--timeout=5',
               'call', dest, path, iface, method]
        if signature:
            cmd += [signature, *args]
        value = self.command(cmd, user=True)
        return json.loads(value) if value.strip() else None

    def power(self, value=None):
        cmd = ['busctl', '--user', '--json=short', '--no-pager', '--auto-start=no',
               '--allow-interactive-authorization=no', '--timeout=5']
        if value is None:
            reply = json.loads(self.command(cmd + ['get-property', DC, DC_PATH, DC, 'PowerSaveMode'], user=True))
            return unwrap(reply)  # get-property JSON has a bare scalar, unlike call
        self.command(cmd + ['set-property', DC, DC_PATH, DC, 'PowerSaveMode', 'i', str(value)], user=True)

    def state(self):
        return parse_state(self.bus('GetCurrentState'))

    def session(self):
        sessions = []
        for row in self.command(['loginctl', 'list-sessions', '--no-legend', '--no-pager']).splitlines():
            sid = row.split()[0]
            props = self.command(['loginctl', 'show-session', sid, '-p', 'Seat', '-p', 'Active',
                                  '-p', 'Class', '-p', 'Type', '-p', 'User', '-p', 'LockedHint'])
            data = dict(line.split('=', 1) for line in props.splitlines() if '=' in line)
            if all(data.get(k) == v for k, v in [('Seat', 'seat0'), ('Active', 'yes'),
                                               ('Class', 'user'), ('Type', 'wayland')]):
                sessions.append((sid, data))
        if len(sessions) != 1 or sessions[0][1].get('LockedHint') != 'no':
            raise Unsupported('requires one unlocked active seat0 Wayland user session')
        sid, data = sessions[0]
        self.user = pwd.getpwuid(int(data['User']))
        runtime = Path(f'/run/user/{self.user.pw_uid}')
        if self.user.pw_uid == 0 or runtime.stat().st_uid != self.user.pw_uid or not stat.S_ISSOCK((runtime / 'bus').stat().st_mode):
            raise Unsupported('invalid desktop user bus')
        self.env = dict(os.environ, HOME=self.user.pw_dir, USER=self.user.pw_name, LOGNAME=self.user.pw_name,
                        XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f'unix:path={runtime}/bus')
        self.env.pop('DBUS_STARTER_ADDRESS', None)
        owned = unwrap(self.bus('NameHasOwner', 's', ['org.gnome.Shell'], dest='org.freedesktop.DBus',
                                path='/org/freedesktop/DBus', iface='org.freedesktop.DBus'))[0]
        if not owned:
            raise Unsupported('seat0 user bus has no GNOME Shell')
        locked = unwrap(self.bus('GetActive', dest='org.gnome.ScreenSaver', path='/org/gnome/ScreenSaver',
                                 iface='org.gnome.ScreenSaver'))[0]
        if not owned or locked:
            raise Unsupported('seat0 session is not an unlocked GNOME session')
        self.result['session'] = {'id': sid, 'uid': self.user.pw_uid}

    def apply(self, mode):
        state = self.state()
        if state['spec'] != self.original['spec']:
            raise RuntimeError('monitor identity changed during test')
        self.changed = True  # uncertain D-Bus return may still have changed hardware
        self.bus('ApplyMonitorsConfig', APPLY_SIGNATURE,
                 apply_arguments(self.original, state['serial'], mode['id']))

    def wait_mode(self, mode):
        deadline = time.monotonic() + 10
        while True:
            state = self.state()
            if mode_matches(state, self.original, mode) and self.power() == 0:
                return state
            if time.monotonic() >= deadline:
                raise RuntimeError(f'Mutter did not settle on requested mode {mode["id"]}')
            time.sleep(0.1)

    def sample(self, state, step):
        path = discover_crc()
        step['crc_path'] = str(path)
        width, height = state['current']['width'], state['current']['height']
        if state['transform'] % 2:
            width, height = height, width
        if state['properties']['layout-mode'] == 1:
            width, height = width / state['scale'], height / state['scale']
        # Clamp to the panel's top-left, then cross both axes without clicks.
        self.pointer.move(-2 * width, -2 * height)
        points = [(width * x, height * y) for x, y in
                  ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8), (0.5, 0.5))]
        x = y = 0
        with CRC(path, self.a.crc_source) as crc:
            start = time.monotonic()
            end = start + self.a.sample_seconds
            moves = 0
            while time.monotonic() < end:
                tx, ty = points[moves % len(points)]
                self.pointer.move(tx - x, ty - y)
                x, y = tx, ty
                moves += 1
                self.log.drain()
                time.sleep(max(0, min(0.12, end - time.monotonic())))
            step['pointer_moves'] = moves
        # Every CRC open starts a fresh kernel ring after the mode has settled.
        step['crc_samples'] = crc.samples
        step['crc'] = crc_metrics(crc.samples, state['current']['hz'])
        if crc.errors:
            step['crc']['reader_errors'] = crc.errors
            step['crc']['status'] = 'INCOMPLETE'
        return step['crc']['status']

    def step(self, name, mode, action=None):
        step = {'name': name, 'requested_mode': mode, 'status': 'INCOMPLETE',
                'start_monotonic': time.monotonic(), 'mode_matches': None,
                'crc': {'status': 'INCOMPLETE', 'fps': None, 'unique_crc': 0}}
        self.result['steps'].append(step)
        mark, log_errors = len(self.log.entries), len(self.log.errors)
        try:
            locked = unwrap(self.bus('GetActive', dest='org.gnome.ScreenSaver',
                                     path='/org/gnome/ScreenSaver', iface='org.gnome.ScreenSaver'))[0]
            if locked:
                raise Unsupported('GNOME session locked during test; no input sent')
            if action:
                action()
            observed = self.wait_mode(mode)
            time.sleep(self.a.settle_seconds)
            step['observed'] = self.wait_mode(mode)
            step['mode_matches'] = True
            step['status'] = self.sample(observed, step)
            after = self.state()
            step['mode_matches'] = mode_matches(after, self.original, mode) and self.power() == 0
            if not step['mode_matches']:
                step['status'] = 'FAIL'
        except Unsupported as error:
            step.update(error=str(error), crc={'status': 'UNSUPPORTED', 'fps': None, 'unique_crc': None})
        except Exception as error:
            step.update(status='FAIL', error=str(error))
        finally:
            try:
                self.log.drain()
                step['kernel_log'] = self.log.entries[mark:]
                step['new_kernel_errors'] = filter_kernel([e['message'] for e in step['kernel_log']])
                step['log_gaps'] = self.log.errors[log_errors:]
                if step['new_kernel_errors']:
                    step['status'] = 'FAIL'
                elif step['log_gaps'] and step['status'] == 'PASS':
                    step['status'] = 'INCOMPLETE'
            except Exception as error:
                step['log_error'] = str(error)
                if step['status'] == 'PASS':
                    step['status'] = 'INCOMPLETE'
            step['end_monotonic'] = time.monotonic()
            save(self.out / f'{len(self.result["steps"]):02d}-{name}.json', step)
            save(self.out / 'result.json', self.result)
        return step['status'] == 'PASS'

    def dpms(self):
        try:
            self.changed = True
            self.power(3)
            if self.power() != 3:
                raise RuntimeError('Mutter did not report PowerSaveMode 3')
            time.sleep(self.a.off_seconds)
        finally:
            self.power(0)

    def run(self):
        try:
            if os.geteuid() != 0:
                raise Unsupported('run as root on the target tablet')
            if not re.search(r'(?:^|\s)androidboot.serialno=' + re.escape(self.a.serial) + r'(?:\s|$)', Path('/proc/cmdline').read_text()):
                raise Unsupported('target serial mismatch')
            if os.uname().release != self.a.kernel:
                raise Unsupported('running kernel differs from --kernel')
            if b'xiaomi,piano\0' not in Path('/proc/device-tree/compatible').read_bytes():
                raise Unsupported('not a piano device tree')
            self.result['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            # Cross-output-directory single writer; abstract socket/host files unused.
            self.lock = open('/run/piano-display-mode-check.lock', 'a')
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.session()
            self.original = self.state()
            self.result['original'] = self.original
            self.result['original_power_save_mode'] = self.power()
            if self.power() != 0:
                raise Unsupported('start with the desktop awake (PowerSaveMode=0)')
            modes = choose_modes(self.original)
            self.result['selected_modes'] = modes
            try:
                self.log = KernelLog()
            except OSError as error:
                raise Unsupported(f'cannot capture new kernel messages: {error}') from error
            self.pointer = Pointer(self.user, self.env)
            if not self.step('original', self.original['current']):
                return
            for index, mode in enumerate([modes[60], modes[120], modes[90], modes[144], modes[120], self.original['current']]):
                if not self.step(f'mode-{index + 1}', mode, lambda m=mode: self.apply(m)):
                    return
            for rate in (120, 144):
                if not self.step(f'dpms-{rate}-before', modes[rate], lambda m=modes[rate]: self.apply(m)):
                    return
                if not self.step(f'dpms-{rate}-after', modes[rate], self.dpms):
                    return
            self.result['status'] = 'PASS'
        except Unsupported as error:
            self.result['errors'].append(str(error))
        except Exception as error:
            self.result['errors'].append(f'{type(error).__name__}: {error}')
            self.result['status'] = 'FAIL'
        finally:
            self.restore()
            statuses = [s['status'] for s in self.result['steps']]
            if 'FAIL' in statuses or self.result['restore'].get('errors'):
                self.result['status'] = 'FAIL'
            elif 'INCOMPLETE' in statuses or 'UNSUPPORTED' in statuses:
                self.result['status'] = 'INCOMPLETE'
            self.result['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            save(self.out / 'result.json', self.result)

    def restore(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        errors = []
        mark = len(self.log.entries) if self.log else 0
        # Each cleanup is independent, so a failed Stop cannot skip screen restore.
        if self.user and self.original:
            for label, operation in [('power_on_before', lambda: self.power(0)),
                                     ('original_mode', lambda: self.apply(self.original['current'])
                                      if self.changed else 'unchanged; no mode/DPMS request issued'),
                                     ('power_on_after', lambda: self.power(0)),
                                     ('readback', lambda: self.wait_mode(self.original['current']))]:
                try:
                    value = operation()
                    self.result['restore'][label] = value if value is not None else 'requested'
                except Exception as error:
                    errors.append(f'{label}: {error}')
        # The final restoration is another modeset. A healthy test must not
        # return PASS based solely on its software readback if that modeset
        # leaves the LM showing a border again. Do not extend a failed run.
        if self.changed and not errors and self.pointer and self.log and self.result['status'] == 'PASS':
            self.result['restore']['crc_validated'] = self.step('restored-original', self.original['current'])
        if self.pointer:
            try:
                self.pointer.close()
            except Exception as error:
                errors.append(f'pointer: {error}')
        if self.log:
            try:
                self.log.drain()
                self.result['restore']['kernel_errors'] = filter_kernel(
                    [entry['message'] for entry in self.log.entries[mark:]])
                if self.result['restore']['kernel_errors']:
                    errors.append('new kernel errors during final restoration')
                if self.log.errors and self.result['status'] == 'PASS':
                    self.result['status'] = 'INCOMPLETE'
                save(self.out / 'kernel-log.json', {'entries': self.log.entries, 'gaps': self.log.errors})
            except Exception as error:
                errors.append(f'kernel log: {error}')
            finally:
                self.log.close()
        if self.lock:
            self.lock.close()
        self.result['restore']['errors'] = errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', required=True, type=Path, help='new private directory')
    parser.add_argument('--serial', required=True, help='expected piano androidboot.serialno')
    parser.add_argument('--kernel', required=True, help='exact expected uname -r (baseline or candidate)')
    parser.add_argument('--label', default='display-mode-check')
    parser.add_argument('--crc-source', choices=('auto', 'lm'), default='auto')
    parser.add_argument('--sample-seconds', type=float, default=3.0)
    parser.add_argument('--settle-seconds', type=float, default=1.0)
    parser.add_argument('--off-seconds', type=float, default=2.0)
    args = parser.parse_args(argv)
    for key, lo, hi in [('sample_seconds', 1, 10), ('settle_seconds', 0.2, 5), ('off_seconds', 1, 5)]:
        value = getattr(args, key)
        if not math.isfinite(value) or not lo <= value <= hi:
            parser.error(f'{key} must be {lo}..{hi} seconds')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', args.serial):
        parser.error('invalid serial')
    check = Check(args)
    def interrupted(signum, frame):
        # Ignore subsequent signals while try/finally restores the display.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        raise RuntimeError(f'interrupted by signal {signum}')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    check.run()
    print(json.dumps({'status': check.result['status'], 'output': str(check.out),
                      'steps': [(s['name'], s['status']) for s in check.result['steps']],
                      'restore_errors': check.result['restore'].get('errors', [])}, ensure_ascii=False))
    return {'PASS': 0, 'FAIL': 1, 'INCOMPLETE': 2}[check.result['status']]


if __name__ == '__main__':
    sys.exit(main())
