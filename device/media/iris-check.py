#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One bounded H.264 hardware decode on a prepared RAM root; no persistent install.

The bundle contains clip.json, test-1080p.h264, reference.framemd5 and firmware/.
Output must be on /run. No software decoder fallback is permitted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


class Result(Exception):
    def __init__(self, status, reason):
        self.status, self.reason = status, reason


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def compare_frames(raw, reference, width, height):
    """Compare packed I420 in presentation order, including count and tail bytes."""
    expected = []
    size = width * height * 3 // 2
    for line in Path(reference).read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        fields = [s.strip() for s in line.split(',')]
        if len(fields) != 6 or int(fields[4]) != size or not re.fullmatch('[0-9a-f]{32}', fields[5]):
            raise ValueError('Invalid host frame-MD5 reference')
        expected.append(fields[5])
    if not expected:
        raise ValueError('Empty host frame-MD5 reference')
    actual = []
    with Path(raw).open('rb') as f:
        while frame := f.read(size):
            if len(frame) != size:
                raise ValueError(f'Partial output frame: {len(frame)}/{size} bytes')
            actual.append(hashlib.md5(frame).hexdigest())
    mismatch = [i for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
    return {'expected_frames': len(expected), 'decoded_frames': len(actual),
            'mismatched_frames': mismatch, 'actual_md5': actual,
            'pass': len(actual) == len(expected) and not mismatch}


def dump_sdam(out):
    # The upstream provider uses register-relative offsets: 0x00..0x3f
    # cannot be read. nvmem core also clips reads at the exported size.
    for dev in Path('/sys/bus/nvmem/devices').glob('*'):
        try:
            node = (dev / 'of_node').resolve()
            if node.name != 'nvram@7200' or node.parent.name != 'pmic@0':
                continue
            datafile = dev / 'nvmem'
            size = datafile.stat().st_size
            count = min(128, size - 0x40)
            if count <= 0:
                raise ValueError(f'Unexpected exported size {size}')
            with datafile.open('rb', buffering=0) as f:
                f.seek(0x40)
                data = f.read(count)
            if len(data) != count:
                raise ValueError(f'Short SDAM read {len(data)}/{count}')
            (out / 'sdam2-offset-40.bin').write_bytes(data)
            print(f'SDAM_DIAG=READ_ONLY path={datafile} exported_size={size} offset=0x40 bytes={len(data)} hex={data.hex()}', flush=True)
            return
        except (OSError, ValueError) as e:
            print(f'SDAM_DIAG=UNAVAILABLE reason={e}', flush=True)
            return
    print('SDAM_DIAG=UNAVAILABLE reason=no PMK8550 nvram@7200 nvmem provider', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    status, reason = 'FAIL', 'check did not complete'
    old_fwpath = None
    output_owned = False
    fwparam = Path('/sys/module/firmware_class/parameters/path')
    started = time.monotonic()
    out = a.output.resolve()

    def command(argv, tag, limit=15, required=True, env=None):
        remaining = 120 - (time.monotonic() - started)
        if remaining <= 0:
            raise Result('FAIL', '120 s decode-check budget exhausted')
        logfile = out / (tag + '.log')
        print('IRIS_COMMAND=' + json.dumps(argv), flush=True)
        with logfile.open('wb') as f:
            p = subprocess.Popen(argv, stdout=f, stderr=subprocess.STDOUT,
                                 env=env, start_new_session=True)
            try:
                rc = p.wait(timeout=min(limit, remaining))
            except BaseException:
                # Also kill children on interruption; never leave gst-launch behind.
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                raise
        text = logfile.read_text(errors='replace')
        print(text, end='' if text.endswith('\n') else '\n', flush=True)
        if required and rc:
            raise Result('FAIL', f'{tag} exited {rc}; see {logfile.name}')
        return rc, text

    try:
        if os.geteuid() != 0:
            raise Result('UNAVAILABLE', 'run as root')
        if not out.is_relative_to('/run') or out == Path('/run'):
            raise Result('UNAVAILABLE', '--output must be a new directory below /run')
        out.mkdir(parents=True, exist_ok=False)
        output_owned = True
        missing = [n for n in ('v4l2-ctl', 'gst-launch-1.0', 'gst-inspect-1.0', 'modprobe', 'dmesg') if not shutil.which(n)]
        if missing:
            raise Result('UNAVAILABLE', 'missing commands: ' + ', '.join(missing) + '; install v4l-utils gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad kmod')
        if os.uname().release != '7.2.6-piano8':
            raise Result('UNAVAILABLE', 'requires the prepared 7.2.6-piano8 RAM candidate')
        cmdline = Path('/proc/cmdline').read_text().split()
        if 'piano.debug_timeout=600' not in cmdline or 'piano.debug=1' not in cmdline:
            raise Result('UNAVAILABLE', 'requires the bounded debug RAM boot')
        uptime = float(Path('/proc/uptime').read_text().split()[0])
        if uptime > 420:
            raise Result('UNAVAILABLE', f'late window: uptime {uptime:.1f}, leave 180 s before auto-return')
        bundle = a.bundle.resolve()
        meta = json.loads((bundle / 'clip.json').read_text())
        for name, digest in meta['inputs'].items():
            path = (bundle / name).resolve()
            if not path.is_relative_to(bundle) or sha(path) != digest:
                raise Result('FAIL', f'bundle hash mismatch: {name}')
        if (meta['width'], meta['height'], meta['frames']) != (1920, 1080, 150):
            raise Result('FAIL', 'expected the fixed 150-frame 1080p clip')
        if shutil.disk_usage(out).free < 600_000_000:
            raise Result('UNAVAILABLE', 'need 600 MB free in /run for I420 output')
        # Independently verify the bundle firmware for this check. Use a RAM-only
        # loader override, then restore the pre-pivot handoff path.
        fwroot = out / 'firmware'
        shutil.copytree(bundle / 'firmware', fwroot)
        old_fwpath = fwparam.read_text().removesuffix('\n')
        fwparam.write_text(str(fwroot) + '\n')
        print('IRIS_FIRMWARE=' + str(fwroot / 'qcom/sm8750/vpu35_4v.mbn') + ' sha256=' + meta['inputs']['firmware/qcom/sm8750/vpu35_4v.mbn'], flush=True)
        command(['modprobe', 'qcom-iris'], 'modprobe-iris')
        command(['modprobe', 'qcom-spmi-sdam'], 'modprobe-sdam', required=False)
        dump_sdam(out)
        command(['v4l2-ctl', '--list-devices'], 'v4l2-devices')
        nodes = []
        for dev in Path('/sys/class/video4linux').glob('video*'):
            if (dev / 'name').read_text().strip() == 'qcom-iris-decoder':
                compatible = (dev / 'device/of_node/compatible').read_bytes().split(b'\0')
                if b'qcom,sm8750-iris' in compatible:
                    nodes.append('/dev/' + dev.name)
        if len(nodes) != 1:
            raise Result('FAIL', f'expected one SM8750 Iris decoder node, found {nodes}')
        node = nodes[0]
        print('IRIS_NODE=' + node, flush=True)
        _, formats = command(['v4l2-ctl', '-d', node, '--list-formats-out', '--list-formats'], 'v4l2-formats')
        if 'H264' not in formats:
            raise Result('FAIL', 'Iris OUTPUT queue did not advertise H264')
        env = dict(os.environ, GST_REGISTRY=str(out / 'gst-registry.bin'), GST_DEBUG_NO_COLOR='1')
        missing_plugins = []
        for element in ('filesrc', 'h264parse', 'v4l2h264dec', 'videoconvert', 'filesink'):
            rc, _ = command(['gst-inspect-1.0', element], 'inspect-' + element, required=False, env=env)
            if rc:
                missing_plugins.append(element)
        if missing_plugins:
            raise Result('UNAVAILABLE', 'missing GStreamer elements: ' + ', '.join(missing_plugins) + '; h264parse needs plugins-bad; v4l2h264dec needs plugins-good and a usable V4L2 H264 decoder node')
        raw = out / 'decoded.i420'
        command(['gst-launch-1.0', '-e', '-v', 'filesrc', f'location={bundle / "test-1080p.h264"}',
                 '!', 'h264parse', '!', 'v4l2h264dec', f'device={node}', '!', 'videoconvert',
                 '!', 'video/x-raw,format=I420', '!', 'filesink', f'location={raw}'],
                'gstreamer-decode', limit=60, env=dict(env, GST_DEBUG='v4l2*:4'))
        comparison = compare_frames(raw, bundle / 'reference.framemd5', 1920, 1080)
        (out / 'comparison.json').write_text(json.dumps(comparison, indent=2) + '\n')
        print('IRIS_FRAMES=' + json.dumps({k: v for k, v in comparison.items() if k != 'actual_md5'}), flush=True)
        for index, digest in enumerate(comparison['actual_md5']):
            print(f'IRIS_FRAME_MD5={index}:{digest}', flush=True)
        if comparison['expected_frames'] != 150 or not comparison['pass']:
            raise Result('FAIL', 'frame count or frame-wise MD5 differs from host software decode')
        status, reason = 'PASS', '150/150 1920x1080 I420 frames exactly match host software decode through the explicit SM8750 Iris V4L2 decoder'
    except Result as e:
        status, reason = e.status, e.reason
    except (Exception, KeyboardInterrupt) as e:
        status, reason = 'FAIL', f'{type(e).__name__}: {e}'
    finally:
        if old_fwpath is not None:
            try:
                fwparam.write_text(old_fwpath or '\0')
            except OSError as e:
                status, reason = 'FAIL', f'could not restore firmware search path: {e}'
        try:
            p = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=5)
            lines = '\n'.join(l for l in p.stdout.splitlines() if re.search(r'iris|venus|hfi|firmware|vpu35', l, re.I))
            print('IRIS_DMESG_BEGIN\n' + lines + '\n' + p.stderr + 'IRIS_DMESG_END', flush=True)
            if output_owned:
                (out / 'dmesg-iris.log').write_text(lines + '\n' + p.stderr)
        except (OSError, subprocess.TimeoutExpired) as e:
            print('IRIS_DMESG_UNAVAILABLE=' + str(e), flush=True)
        print(f'IRIS_RESULT={status} reason={reason}', flush=True)
    return {'PASS': 0, 'FAIL': 1, 'UNAVAILABLE': 2}[status]


if __name__ == '__main__':
    sys.exit(main())
