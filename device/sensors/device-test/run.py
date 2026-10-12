#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One-shot SSC check using the pinned, unmodified libssc CLI. No installation."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
import uuid

TYPES = {'accelerometer': 'accel', 'gyroscope': 'gyro', 'light': 'ambient_light', 'proximity': 'proximity'}
CRITERION = 'Resting tablet: |a| approximately 9.8 m/s^2; require >=2 samples, median 7.8..11.8 m/s^2. SSC_ACCEL_G is m/s^2, not multiples of g.'
SENSOR_POLL_SECONDS = 30
CLIENT_SECONDS = 70  # registry <=30 + physical discovery <=30 + samples/close
DAEMON_SECONDS = 75
BOOT_STATE = Path('/var/tmp/ssc-test')


def parse_sensor(kind, text, returncode):
    """Parse upstream 0.4.4 output, preserving errors and discovery separately."""
    samples, invalid = [], 0
    for line in text.splitlines():
        match = re.fullmatch(r'(Accelerometer|Gyroscope) sensor measurement: X=(\S+) Y=(\S+) Z=(\S+) (.+)', line)
        light = re.fullmatch(r'Light sensor measurement: (\S+) Lux', line)
        near = re.fullmatch(r'Proximity sensor measurement: (NEAR|FAR)', line)
        if match and match[1].lower() == kind:
            value = dict(zip(('x', 'y', 'z'), map(float, match.group(2, 3, 4))))
            value['upstream_unit'] = match[5]
        elif light and kind == 'light':
            value = {'lux': float(light[1])}
        elif near and kind == 'proximity':
            value = {'near': near[1] == 'NEAR'}
        else:
            continue
        if any(isinstance(v, float) and not math.isfinite(v) for v in value.values()):
            invalid += 1
        else:
            samples.append(value)
    discovery = re.search(r"Discovered '([^']+)' sensor \((\d+) (\d+)\)", text)
    attributes = {key: value.strip() for key, value in re.findall(
        r'  (name|vendor|data-type|stream-type|sample-rate|available|mount-matrix): (.*)', text)}
    unavailable = bool(re.search(r"No '" + TYPES[kind] + r"' sensor available", text))
    # libqmi's optional debug pretty-printer can say "translated = ERROR"
    # even when libssc successfully decodes the payload. Preserve that text,
    # but only actual CLI failures / GLib warning records affect the verdict.
    errors = [line for line in text.splitlines() if line.startswith('Unable to ') or
              re.search(r'\b(?:WARNING|CRITICAL|ERROR)\s*\*\*:', line)]
    trace_diagnostics = [line for line in text.splitlines() if 'translated =  ERROR' in line]
    result = 'PASS' if samples and returncode == 0 and not invalid and not errors else ('UNAVAILABLE' if unavailable and not samples else 'FAIL')
    reason = ('default sensor not advertised' if unavailable else
              'non-finite samples' if invalid else
              '; '.join(errors)[-1000:] if errors else
              f'client exit {returncode}' if returncode else
              'no samples' if not samples else 'samples received')
    return dict(sensor=kind, result=result, reason=reason, returncode=returncode,
                discovered=bool(discovery),
                suid=discovery.group(2, 3) if discovery else None,
                attributes=attributes, samples=samples, sample_count=len(samples), invalid_samples=invalid,
                trace_diagnostics=trace_diagnostics)


def aggregate(rows, daemon_ok):
    accel = rows['accelerometer']
    magnitudes = [math.sqrt(sum(s[c] ** 2 for c in ('x', 'y', 'z'))) for s in accel['samples']]
    first = magnitudes[0] if magnitudes else None
    median = statistics.median(magnitudes) if magnitudes else None
    if not daemon_ok:
        result, reason = 'FAIL', 'hexagonrpcd exited before clients completed; inspect daemon.log'
    elif accel['result'] == 'UNAVAILABLE':
        result, reason = 'UNAVAILABLE', 'SSC did not advertise a default accelerometer'
    elif accel['result'] != 'PASS':
        result, reason = 'FAIL', 'accelerometer: ' + accel['reason']
    elif len(magnitudes) < 2 or not 7.8 <= median <= 11.8:
        result, reason = 'FAIL', 'accelerometer samples fail the resting-tablet magnitude/count criterion'
    else:
        failures = [k for k, v in rows.items() if v['result'] == 'FAIL']
        result, reason = ('FAIL', 'other sensor failures: ' + ', '.join(failures)) if failures else ('PASS', 'plausible acceleration and samples from all advertised requested types')
    return dict(result=result, reason=reason, accel_samples=len(magnitudes), accel_first_m_s2=first,
                accel_median_m_s2=median, criterion=CRITERION)


def empty_suid_reply(kind, text, code):
    """Only retry the CLI's specific empty-SUID initialization result."""
    return (code == 254 and f"No '{TYPES[kind]}' sensor available" in text and
            not re.search(r'\b(?:WARNING|CRITICAL|ERROR)\s*\*\*:', text))


def collect_sensors(command, out, daemon, children, env, kinds=None):
    """Poll one-shot ssccli discovery; never restart the daemon or hide attempts."""
    kinds = tuple(kinds or TYPES)
    states = {kind: dict(child=None, log=None, attempt=0, retry_at=0,
                        deadline=None, found=False, attempts=[]) for kind in kinds}
    start = time.monotonic()
    global_deadline = start + CLIENT_SECONDS
    rows = {}

    def finish(kind, state, row):
        shutil.copyfile(state['path'], out/(kind+'.log'))
        row['discovery_attempts'] = state['attempts']
        row['elapsed_seconds'] = round(time.monotonic()-start, 3)
        rows[kind] = row

    try:
        while len(rows) < len(states):
            now = time.monotonic()
            if daemon.poll() is not None:
                raise RuntimeError('hexagonrpcd exited during discovery; inspect daemon.log and attempt logs')
            for kind, state in states.items():
                if kind in rows:
                    continue
                child = state['child']
                if child is None:
                    if state['deadline'] is not None and now >= state['deadline']:
                        state['last']['reason'] = 'default sensor not advertised during 30-second empty-SUID polling'
                        finish(kind, state, state['last'])
                        continue
                    if now < state['retry_at']:
                        continue
                    state['attempt'] += 1
                    state['path'] = out/f"{kind}.attempt-{state['attempt']:02d}.log"
                    state['log'] = state['path'].open('wb')
                    state['attempt_start'] = now
                    child = subprocess.Popen([*command, '--debug', '--sensor', kind, '--timeout', '5'],
                                             stdout=state['log'], stderr=subprocess.STDOUT,
                                             env=env, start_new_session=True)
                    children.append(child); state['child'] = child
                timed_out = False
                if child.poll() is None and state['deadline'] is not None and now >= state['deadline'] and not state['found']:
                    text = state['path'].read_text(errors='replace')
                    state['found'] = bool(re.search(r"Discovered '" + TYPES[kind] + r"' sensor \(", text))
                    # A discovered sensor may finish its five-second stream.
                    if not state['found']:
                        stop(child); timed_out = True
                if child.poll() is None and now >= global_deadline:
                    stop(child); timed_out = True
                if child.poll() is None:
                    continue
                state['log'].close(); state['log'] = None
                text = state['path'].read_text(errors='replace')
                row = parse_sensor(kind, text, child.returncode)
                state['attempts'].append(dict(log=state['path'].name, returncode=child.returncode,
                    elapsed_seconds=round(time.monotonic()-state['attempt_start'], 3), timed_out=timed_out))
                if timed_out:
                    row.update(result='FAIL', reason='active SSC lookup or sample phase exceeded its deadline')
                if not timed_out and empty_suid_reply(kind, text, child.returncode):
                    if state['deadline'] is None:
                        state['deadline'] = time.monotonic() + SENSOR_POLL_SECONDS
                    if time.monotonic() < state['deadline'] and time.monotonic() < global_deadline:
                        state['last'] = row
                        state['child'] = None
                        state['retry_at'] = time.monotonic() + 1
                        continue
                finish(kind, state, row)
            if len(rows) < len(states):
                time.sleep(0.1)  # Supervisor polling, not a device initialization delay.
    finally:
        for state in states.values():
            if state['child'] is not None:
                stop(state['child'])
            if state['log'] is not None:
                state['log'].close()
    return rows


def stop(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            child.wait()
            return
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def kernel_log(out, when):
    try:
        proc = subprocess.run(['dmesg', '--color=never'], capture_output=True, text=True, timeout=5)
        text = '\n'.join(line for line in proc.stdout.splitlines() if
                         re.search(r'fastrpc|adsp|sensors|qrtr|smmu|remoteproc', line, re.I))
        (out/('kernel-' + when + '.log')).write_text(text + '\n' + proc.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        (out/('kernel-' + when + '.log')).write_text(str(exc) + '\n')


def registry_hashes(root):
    hashes = {}
    for f in sorted(root.rglob('*')):
        if f.is_symlink() or (not f.is_dir() and not f.is_file()):
            raise RuntimeError('non-regular registry entry: ' + str(f))
        if f.is_file():
            with f.open('rb') as stream:
                hashes[str(f.relative_to(root))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return hashes


def copy_registry(pristine, scratch):
    """Create new inodes; never link writes back to the pristine bundle/backup."""
    before = registry_hashes(pristine)
    scratch.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name in before:
        dest = scratch/name
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(pristine/name, dest)
        dest.chmod(0o600)
        if (pristine/name).stat().st_ino == dest.stat().st_ino and (pristine/name).stat().st_dev == dest.stat().st_dev:
            raise RuntimeError('registry copy shares an inode with pristine input')
    if registry_hashes(scratch) != before or registry_hashes(pristine) != before:
        raise RuntimeError('registry changed while making the scratch copy')
    return before


def claim_boot(boot_id, state_dir, force=False):
    """Under the session flock, consume a boot before any DSP interaction.

    No history cannot establish freshness for legacy v1-v3 runs: enroll that
    boot and fail closed once. A different subsequent boot is admissible.
    """
    boot_id = str(uuid.UUID(boot_id.strip()))
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    history = state_dir/'boot-history.json'
    last = state_dir/'last-boot-id'
    seen = set()
    if history.exists():
        data = json.loads(history.read_text())
        if (not isinstance(data, dict) or data.get('schema') != 1 or
                not isinstance(data.get('seen_boot_ids'), list) or
                any(not isinstance(value, str) for value in data['seen_boot_ids'])):
            raise ValueError('invalid shared boot history')
        seen.update(str(uuid.UUID(value)) for value in data['seen_boot_ids'])
    if last.exists():
        seen.add(str(uuid.UUID(last.read_text().strip())))
    first_use = not seen
    fresh = not first_use and boot_id not in seen
    reason = ('no earlier boot identity; recorded baseline, normal reboot required' if first_use else
              'this boot was already consumed by an SSC run' if boot_id in seen else
              'boot differs from all recorded SSC boots')
    seen.add(boot_id)
    for path, text in [(history, json.dumps({'schema': 1, 'seen_boot_ids': sorted(seen)}, indent=2)+'\n'),
                       (last, boot_id+'\n')]:
        temp = path.with_name(path.name+'.tmp')
        with temp.open('w') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        temp.replace(path)
    directory = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return dict(boot_id=boot_id, fresh=fresh, allowed=fresh or force, forced=force,
                first_use=first_use, reason=reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/var/tmp/ssc-test'))
    parser.add_argument('--force', action='store_true', help='allow an unverified/reused boot; still print SSC_FRESH_BOOT=NO')
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    base = args.output.resolve()
    if not (base == Path('/var/tmp/ssc-test') or Path('/var/tmp/ssc-test') in base.parents or Path('/run') in base.parents):
        parser.error('output must be /var/tmp/ssc-test, its child, or below /run')
    if os.geteuid() != 0:
        parser.error('run as root; no services or packages will be installed')
    os.umask(0o077)
    base.mkdir(parents=True, exist_ok=True)
    lock = open('/run/ssc-device-test.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('another SSC test owns /run/ssc-device-test.lock')
    out = base / ('run-' + time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid()))
    out.mkdir()
    print('SSC_OUTPUT=' + str(out), flush=True)
    print('SSC_CRITERION=' + CRITERION, flush=True)
    print('SSC_TIMING=registry<=30s empty-SUID-poll<=30s samples~5s client<=70s daemon<=75s', flush=True)
    children, streams, readers = [], [], []
    pristine = scratch = pristine_hashes = None
    admission = None
    summary = dict(result='FAIL', reason='test interrupted before completion', accel_samples=0,
                   accel_first_m_s2=None, accel_median_m_s2=None)
    def interrupted(sig, frame):
        raise RuntimeError('interrupted by signal ' + str(sig))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        facts = {'kernel': platform.release(), 'machine': platform.machine()}
        facts['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        facts['proc_version'] = Path('/proc/version').read_text().strip()
        notes = Path('/sys/kernel/notes')
        if notes.is_file():
            facts['kernel_notes_sha256'] = hashlib.sha256(notes.read_bytes()).hexdigest()
        facts['fastrpc_ls'] = subprocess.run(['sh', '-c', 'ls -l /dev/fastrpc*'], capture_output=True, text=True).stdout
        facts['qrtr_sysfs'] = {str(f): f.read_text(errors='replace') for f in Path('/sys/bus/qrtr/devices').glob('*/uevent')}
        facts['remoteproc'] = {str(f): f.read_text().strip() for f in Path('/sys/class/remoteproc').glob('*/state')}
        for name in ('compatible', 'model'):
            facts[name] = (Path('/sys/firmware/devicetree/base') / name).read_bytes().decode().replace('\0', ' ').strip()
        (out/'facts.json').write_text(json.dumps(facts, indent=2)+'\n')
        print(json.dumps(facts, indent=2), flush=True)
        kernel_log(out, 'before')
        if facts['kernel'] != '7.2.6-piano8' or 'xiaomi,piano' not in facts['compatible'].split():
            raise RuntimeError('bundle requires installed 7.2.6-piano8 on xiaomi,piano')
        if not Path('/dev/fastrpc-adsp-secure').is_char_device():
            summary.update(result='UNAVAILABLE', reason='/dev/fastrpc-adsp-secure is absent')
            return 2
        # Do not interfere with an existing owner or start a second file server.
        for comm in Path('/proc').glob('[0-9]*/comm'):
            try:
                if comm.read_text().strip() in ('hexagonrpcd', 'ssccli', 'iio-sensor-proxy'):
                    raise RuntimeError('existing sensor process: ' + str(comm.parent))
            except FileNotFoundError:
                pass
        try:
            admission = claim_boot(facts['boot_id'], BOOT_STATE, args.force)
        except (OSError, ValueError, TypeError) as exc:
            admission = dict(boot_id=facts['boot_id'], fresh=False, allowed=False,
                             forced=args.force, reason='shared boot history error: ' + str(exc))
        print('SSC_FRESH_BOOT=' + ('YES' if admission['fresh'] else 'NO'), flush=True)
        (out/'fresh-boot.json').write_text(json.dumps(admission, indent=2)+'\n')
        if not admission['allowed']:
            summary.update(result='UNAVAILABLE', reason=admission['reason'])
            return 2
        try:
            qrtr = subprocess.run([sys.executable, str(bundle/'qrtr-lookup.py')], capture_output=True, text=True, timeout=5)
            (out/'qrtr.log').write_text(qrtr.stdout + qrtr.stderr)
            services = json.loads(qrtr.stdout) if qrtr.returncode == 0 else None
        except subprocess.TimeoutExpired:
            (out/'qrtr.log').write_text('Python lookup exceeded 5 seconds; continue with libssc discovery.\n')
            services = None
        print('SSC_QRTR_400=' + json.dumps(services), flush=True)
        if services == []:
            summary.update(result='UNAVAILABLE', reason='QRTR lookup completed with no SSC service 400')
            return 2
        # Lookup failure is diagnostic; libssc has its own QRTR discovery path.
        manifest = json.loads((bundle/'payload.json').read_text())
        source = bundle/'private-input/hexagonfs'
        required = [source/'sensors/odm/config/json.lst', source/'sensors/sns_reg.conf']
        if not all(p.is_file() for p in required) or not any((source/'sensors/registry/registry').glob('*')):
            summary.update(result='UNAVAILABLE', reason='missing local stock config/sns_reg.conf/runtime registry; see README')
            return 2
        for name, digest in manifest['sha256'].items():
            f = bundle/name
            if f.is_symlink() or hashlib.file_digest(f.open('rb'), 'sha256').hexdigest() != digest:
                raise RuntimeError('payload hash mismatch: ' + name)
        root = out/'hexagonfs'
        # The daemon's ordinary mapped files remain read-only. The explicit -w
        # mapping is a fresh private scratch copy on every invocation.
        shutil.copytree(source, root, ignore=lambda d, names: ['registry'] if Path(d) == source/'sensors' else [])
        scratch_parent = base/'scratch'
        scratch_parent.mkdir(mode=0o700, exist_ok=True)
        if scratch_parent.is_symlink() or scratch_parent.resolve().parent != base:
            raise RuntimeError('scratch parent must be a real directory under output')
        scratch_run = scratch_parent/out.name
        scratch_run.mkdir(mode=0o700, exist_ok=False)
        pristine, scratch = source/'sensors/registry', scratch_run/'registry'
        pristine_hashes = copy_registry(pristine, scratch)
        (out/'registry-pristine.json').write_text(json.dumps(pristine_hashes, indent=2)+'\n')
        (out/'registry-before.json').write_text(json.dumps(registry_hashes(scratch), indent=2)+'\n')
        print('SSC_SCRATCH=' + str(scratch), flush=True)
        (root/'socinfo').mkdir(exist_ok=True)
        for name in ('soc_id', 'revision', 'machine', 'family', 'platform_subtype', 'platform_subtype_id', 'platform_version', 'hw_platform'):
            p = Path('/sys/devices/soc0') / name
            if p.is_file():
                (root/'socinfo'/name).write_bytes(p.read_bytes())
        for name in ('dsp/adsp', 'acdb'):
            (root/name).mkdir(parents=True, exist_ok=True)
        loader = [str(bundle/'lib/ld-linux-aarch64.so.1'), '--library-path', str(bundle/'lib')]
        env = dict(os.environ, LC_ALL='C.UTF-8', HOME=str(out), TMPDIR=str(out), XDG_CACHE_HOME=str(out/'cache'), PYTHONDONTWRITEBYTECODE='1')
        env.pop('LD_PRELOAD', None)
        env.pop('LD_LIBRARY_PATH', None)
        log = (out/'daemon.log').open('wb'); streams.append(log)
        # PTY output makes upstream stdio line buffered, so timeout cannot lose
        # the last short file-request/attach log in a userspace stdio buffer.
        master, slave = os.openpty()
        try:
            daemon = subprocess.Popen(['timeout', '--signal=TERM', '--kill-after=2s', f'{DAEMON_SECONDS}s', *loader,
                                       str(bundle/'bin/hexagonrpcd'), '-f', '/dev/fastrpc-adsp-secure', '-d', 'adsp', '-s', '-R', str(root), '-w', str(scratch)],
                                      stdin=subprocess.DEVNULL, stdout=slave, stderr=slave, env=env, start_new_session=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        children.append(daemon)
        def drain(fd, stream):
            try:
                while data := os.read(fd, 65536):
                    stream.write(data); stream.flush()
            except OSError:  # Linux PTYs report EIO after the last slave closes.
                pass
            finally:
                os.close(fd)
        reader = threading.Thread(target=drain, args=(master, log), daemon=True)
        reader.start(); readers.append(reader)
        rows = collect_sensors([*loader, str(bundle/'bin/ssccli')], out, daemon, children, env)
        for kind in TYPES:
            (out/(kind+'.json')).write_text(json.dumps(rows[kind], indent=2, allow_nan=False)+'\n')
            print('SSC_SENSOR=' + kind + ' RESULT=' + rows[kind]['result'] + ' SAMPLES=' + str(rows[kind]['sample_count']), flush=True)
        (out/'sensors.json').write_text(json.dumps([{k: v for k, v in row.items() if k != 'samples'} for row in rows.values()], indent=2)+'\n')
        summary = aggregate(rows, daemon.poll() is None)
        summary['daemon_status_before_cleanup'] = daemon.poll()
    except Exception as exc:
        summary.update(result='FAIL', reason=str(exc))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        for child in reversed(children):
            stop(child)
        for reader in readers:
            reader.join(timeout=3)
        for stream in streams:
            stream.close()
        if pristine_hashes is not None:
            try:
                after = registry_hashes(scratch)
                unchanged = registry_hashes(pristine) == pristine_hashes
                (out/'registry-after.json').write_text(json.dumps(after, indent=2)+'\n')
                summary['registry_pristine_unchanged'] = unchanged
                summary['scratch'] = str(scratch)
                summary['registry_changed_files'] = sorted(n for n in set(after) | set(pristine_hashes)
                    if after.get(n) != pristine_hashes.get(n))
                print('SSC_REGISTRY_PRISTINE_UNCHANGED=' + ('YES' if unchanged else 'NO'), flush=True)
                if not unchanged:
                    summary.update(result='FAIL', reason='pristine registry changed; preserve all evidence')
            except Exception as exc:
                summary.update(result='FAIL', reason='registry audit: ' + str(exc))
        kernel_log(out, 'after')
        if admission is not None:
            summary['fresh_boot'] = admission
        summary['started_pids'] = [c.pid for c in children]
        summary['processes_after_cleanup'] = [c.returncode for c in children]
        (out/'result.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
        print('SSC_RESULT=' + summary['result'] + ' ' + summary['reason'].replace('\n', ' '), flush=True)
        magnitude = summary['accel_median_m_s2']
        print('SSC_SAMPLES=' + str(summary['accel_samples']) + ' SSC_ACCEL_G=' + (f'{magnitude:.6f}' if magnitude is not None else 'NA'), flush=True)
    return 0 if summary['result'] == 'PASS' else 2 if summary['result'] == 'UNAVAILABLE' else 1


if __name__ == '__main__':
    sys.exit(main())
