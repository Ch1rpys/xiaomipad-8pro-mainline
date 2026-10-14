#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded SSH video acceptance: four 8-bit 4:2:0 codecs, 1080p/2160p, 150 frames.

Host: Python 3, ffmpeg (x264/x265/vpx/SVT-AV1), ffprobe, ssh.
Target: Python GI Gst/GstVideo/GstPlay, GStreamer good/bad/base-apps.
No package installation, rank override, service changes, driver rebind or reboot.
Output contains private device identity. Keep it outside the public repository.
Optional sudo password is read only from stdin, solely for read-only dmesg and the installed kernel hash.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

CODECS = {'h264': ('libx264', ['-preset', 'veryfast', '-crf', '24']),
          'h265': ('libx265', ['-preset', 'ultrafast', '-crf', '24', '-x265-params', 'pools=4:frame-threads=2']),
          'vp9': ('libvpx-vp9', ['-deadline', 'realtime', '-cpu-used', '6', '-row-mt', '1', '-crf', '32', '-b:v', '0']),
          'av1': ('libsvtav1', ['-preset', '10', '-crf', '35', '-svtav1-params', 'lp=4'])}
SIZES = {'1080p': (1920, 1080), '2160p': (3840, 2160)}


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def worker(job):
    """One process per pipeline; no persistent target component."""
    import resource
    import gi
    gi.require_version('Gst', '1.0')
    gi.require_version('GstVideo', '1.0')
    from gi.repository import Gst, GstVideo
    Gst.init(None)
    mode = job['mode']
    result = {'mode': mode, 'status': 'FAIL', 'elements': [], 'frames': [], 'count': 0,
              'gst_version': Gst.version_string(), 'rank_override': os.getenv('GST_PLUGIN_FEATURE_RANK')}
    width, height = job['width'], job['height']
    caps = f'video/x-raw,format=I420,width={width},height={height}'
    output = None
    info = None
    callback_errors = []

    def trace_buffer(_pad, probe, label):
        if probe.type & Gst.PadProbeType.BUFFER:
            result.setdefault('decoder_buffers', {}).setdefault(label, 0)
            result['decoder_buffers'][label] += 1
        return Gst.PadProbeReturn.OK

    def added(_bin, _sub, element):
        factory = element.get_factory()
        if factory:
            name = factory.get_name()
            if name not in result['elements']:
                result['elements'].append(name)
            if mode == 'decode' and 'Decoder/Video' in factory.get_metadata('klass'):
                for label in ('sink', 'src'):
                    element.get_static_pad(label).add_probe(Gst.PadProbeType.BUFFER, trace_buffer, label)
            if 'Decoder/Video' in factory.get_metadata('klass') or 'Encoder/Video' in factory.get_metadata('klass'):
                result.setdefault('codec_elements', []).append({'factory': name, 'rank': factory.get_rank(),
                    'plugin_file': factory.get_plugin().get_filename()})

    def sample(sink):
        nonlocal info
        try:
            s = sink.emit('pull-sample')
            if info is None:
                info = GstVideo.VideoInfo.new_from_caps(s.get_caps())
                result['output_caps'] = s.get_caps().to_string()
            buf = s.get_buffer()
            ok, mapped = buf.map(Gst.MapFlags.READ)
            if not ok:
                raise RuntimeError('map failed')
            try:
                # Explicitly exclude alignment padding, including 1088-line V4L2 buffers.
                data = memoryview(mapped.data)
                raw = b''.join(data[info.offset[p] + y * info.stride[p]:
                                           info.offset[p] + y * info.stride[p] + w]
                               for p, w, h in ((0, width, height), (1, width // 2, height // 2),
                                               (2, width // 2, height // 2)) for y in range(h))
                output.write(raw)
                result['frames'].append({'md5': hashlib.md5(raw).hexdigest(), 'pts_ns': int(buf.pts)})
                result['count'] += 1
            finally:
                buf.unmap(mapped)
            return Gst.FlowReturn.OK
        except Exception as e:
            callback_errors.append(str(e))
            return Gst.FlowReturn.ERROR

    def handoff(_sink, _buffer, _pad):
        result['count'] += 1

    play = None
    if mode in ('decode', 'source'):
        output = open(job['raw'], 'wb')
        sink = Gst.parse_bin_from_description(
            f'videoconvert ! {caps} ! appsink name=frames emit-signals=true sync=false max-buffers=2 drop=false', True)
        sink.get_by_name('frames').connect('new-sample', sample)
    else:
        sink = Gst.ElementFactory.make('fakesink')
        sink.set_property('sync', mode == 'player')
        sink.set_property('signal-handoffs', True)
        sink.connect('handoff', handoff)
    if mode == 'encode':
        codec = job['codec']
        pipeline = Gst.parse_launch(
            f'videotestsrc num-buffers=150 pattern=ball ! video/x-raw,format=NV12,width={width},height={height},framerate=30/1 '
            f'! v4l2{codec}enc extra-controls="controls,video_bitrate={job["bitrate"]}" '
            f'! {codec}parse ! matroskamux ! filesink location={job["encoded"]}')
        # Elements are already present after parse_launch.
        it = pipeline.iterate_recurse()
        while True:
            status, el = it.next()
            if status != Gst.IteratorResult.OK:
                break
            added(pipeline, pipeline, el)
    elif mode == 'source':
        pipeline = Gst.parse_launch(
            f'videotestsrc num-buffers=150 pattern=ball ! video/x-raw,format=NV12,width={width},height={height},framerate=30/1 ! identity name=tail')
        pipeline.add(sink)
        pipeline.get_by_name('tail').link(sink)
    elif mode == 'player':
        gi.require_version('GstPlay', '1.0')
        from gi.repository import GstPlay
        play = GstPlay.Play(video_renderer=GstPlay.PlayVideoOverlayVideoRenderer.new_with_sink(None, sink))
        pipeline = play.get_pipeline()
        result['player_factory'] = pipeline.get_factory().get_name()
        play.set_uri(Path(job['clip']).as_uri())
    else:
        pipeline = Gst.ElementFactory.make('playbin3')
        pipeline.set_property('uri', Path(job['clip']).as_uri())
        pipeline.set_property('video-sink', sink)
    if mode not in ('source', 'encode'):
        pipeline.set_property('audio-sink', Gst.ElementFactory.make('fakesink'))
        pipeline.set_property('text-sink', Gst.ElementFactory.make('fakesink'))
    pipeline.connect('deep-element-added', added)
    bus = play.get_message_bus() if play else pipeline.get_bus()
    before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.monotonic()
    if play:
        play.play()
    else:
        pipeline.set_state(Gst.State.PLAYING)
    try:
        while time.monotonic() - started < 60:
            msg = bus.timed_pop(Gst.SECOND)
            if msg is None:
                continue
            if play:
                kind = GstPlay.play_message_parse_type(msg)
                if kind == GstPlay.PlayMessage.END_OF_STREAM:
                    result['status'] = 'PASS'
                    break
                if kind == GstPlay.PlayMessage.ERROR:
                    result['error'] = str(GstPlay.play_message_parse_error(msg))
                    break
            elif msg.type == Gst.MessageType.EOS:
                result['eos_source'] = msg.src.get_path_string()
                result['status'] = 'PASS'
                break
            elif msg.type == Gst.MessageType.ERROR:
                error, debug = msg.parse_error()
                result['error'] = str(error)
                result['debug'] = debug
                break
        else:
            result['error'] = 'pipeline did not reach EOS within 60 seconds'
        elapsed = time.monotonic() - started
        after = resource.getrusage(resource.RUSAGE_SELF)
        result['seconds'] = elapsed
        result['cpu_seconds'] = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
        result['cpu_percent_one_core'] = result['cpu_seconds'] / elapsed * 100
        result['fps'] = result['count'] / elapsed
        Path(job['dot']).write_text(Gst.debug_bin_to_dot_data(pipeline, Gst.DebugGraphDetails.ALL))
    finally:
        if play:
            play.stop()
        pipeline.set_state(Gst.State.NULL)
        if output:
            output.close()
    if callback_errors:
        result['status'], result['callback_errors'] = 'FAIL', callback_errors
    print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'PASS' else 1


class Check:
    def __init__(self, args):
        self.a = args
        self.out = args.output.resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(__file__, self.out / 'runner.py')
        self.password = sys.stdin.buffer.readline() if args.sudo_password_stdin else None
        if self.password is not None and not self.password.strip():
            raise ValueError('empty sudo password')
        self.remote = None
        self.ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', args.ssh]
        self.guard = (f'test "$(sed -n \'s/.*androidboot.serialno=\\([^ ]*\\).*/\\1/p\' /proc/cmdline)" = {shlex.quote(args.serial)} '
                      f'&& test "$(uname -r)" = {shlex.quote(args.kernel)} || exit 70; ')
        self.result = {'schema': 1, 'status': 'FAIL', 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                       'script_sha256': sha(__file__), 'selection': {'codecs': getattr(args, 'codecs', []), 'sizes': getattr(args, 'sizes', []), 'only': getattr(args, 'only', 'all')}, 'inputs': [], 'decode': [], 'encode': [],
                       'measurement': '150 frames at 30 fps; 8-bit 4:2:0; CPU 100% = one logical core; benchmark includes startup/drain, excludes hashing; player is realtime GstPlay with fakesink'}

    def run(self, argv, tag, timeout=120, data=None, required=True):
        with (self.out / 'commands.jsonl').open('a') as f:
            f.write(json.dumps({'tag': tag, 'argv': argv}) + '\n')
        started = time.monotonic()
        with (self.out / (tag + '.log')).open('wb') as log:
            p = subprocess.run(argv, input=data, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        if required and p.returncode:
            raise RuntimeError(f'{tag} exited {p.returncode}; see {tag}.log')
        return p.returncode, (self.out / (tag + '.log')).read_text(errors='replace'), time.monotonic() - started

    def remote_run(self, command, tag, **kwargs):
        return self.run(self.ssh + [self.guard + command], tag, **kwargs)

    def upload(self, path, dest):
        # Authenticate the device on every transfer as well as every command.
        self.remote_run('cat > ' + shlex.quote(dest), 'upload-' + Path(path).name, data=Path(path).read_bytes())

    def download(self, name, local):
        with open(local, 'wb') as f:
            subprocess.run(self.ssh + [self.guard + 'cat ' + shlex.quote(self.remote + '/' + name)],
                           stdout=f, check=True, timeout=120)

    def pipeline(self, mode, tag, **kw):
        job = dict(mode=mode, dot=self.remote + '/' + tag + '.dot', **kw)
        save(self.out / (tag + '-job.json'), job)
        self.upload_json(job, self.remote + '/job.json')
        _, text, _ = self.remote_run(
            f'timeout -k 5s 75s env GST_DEBUG_NO_COLOR=1 GST_DEBUG={shlex.quote(getattr(self.a, 'gst_debug', 'v4l2*:4,decodebin3:4'))} '
            f'python3 {shlex.quote(self.remote)}/check.py --worker {shlex.quote(self.remote)}/job.json', tag, timeout=90, required=False)
        try:
            result = json.loads(next(line for line in reversed(text.splitlines())
                                     if line.startswith('{"mode":')))
        except (ValueError, IndexError, StopIteration):
            return {'status': 'FAIL', 'error': 'worker did not return JSON; see ' + tag + '.log'}
        self.download(tag + '.dot', self.out / (tag + '.dot'))
        save(self.out / (tag + '.json'), result)
        return result

    def upload_json(self, data, dest):
        self.remote_run('cat > ' + shlex.quote(dest), 'upload-job', data=json.dumps(data).encode())

    def ff(self, argv, tag):
        return self.run([self.a.ffmpeg, '-hide_banner', '-nostdin', '-y'] + argv, tag, timeout=600)

    def probe(self, path, tag):
        _, text, _ = self.run([self.a.ffprobe, '-v', 'error', '-count_frames', '-show_streams',
                              '-show_format', '-of', 'json', str(path)], tag)
        return json.loads(text)

    def psnr(self, raw, decoded, width, height, tag):
        stats = self.out / (tag + '-frames.log')
        _, text, _ = self.ff(['-f', 'rawvideo', '-pixel_format', 'yuv420p', '-video_size', f'{width}x{height}', '-framerate', '30',
                             '-i', str(raw), '-i', str(decoded), '-lavfi',
                             f'[0:v]settb=1/30,setpts=N[a];[1:v]format=yuv420p,settb=1/30,setpts=N[b];[a][b]psnr=stats_file={stats}',
                             '-f', 'null', '-'], tag)
        match = re.search(r'PSNR y:[^\n]*average:([\d.inf]+)', text)
        return match.group(1) if match else None

    def execute(self):
        for cmd in (self.a.ffmpeg, self.a.ffprobe):
            self.run([cmd, '-version'], Path(cmd).name + '-version')
        _, before, _ = self.remote_run(
            "python3 -c 'import json,os,pathlib; print(json.dumps({\"kernel\":os.uname().release,\"cmdline\":pathlib.Path(\"/proc/cmdline\").read_text(),\"boot_id\":pathlib.Path(\"/proc/sys/kernel/random/boot_id\").read_text()}))'; "
            "systemctl show piano-kbd-monitor.service bluetooth.service -p Id -p MainPID -p ActiveState; "
            "dpkg-query -W showtime gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad; "
            "sha256sum /boot/vmlinuz-$(uname -r) /boot/config-$(uname -r) /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideo4linux2.so; "
            "cat /usr/lib/python3/dist-packages/showtime/play.py", 'identity-before')
        self.result['identity_log'] = 'identity-before.log'
        if self.password:
            self.remote_run("sudo -S -p '' dmesg", 'dmesg-before', data=self.password)
            self.remote_run("sudo -S -p '' sha256sum /boot/vmlinuz-" + self.a.kernel, 'kernel-sha256', data=self.password)
        _, remote, _ = self.remote_run('mktemp -d /tmp/piano-video-check.XXXXXXXX', 'mktemp')
        self.remote = remote.strip()
        if not re.fullmatch(r'/tmp/piano-video-check\.[A-Za-z0-9]+', self.remote):
            raise RuntimeError('unexpected temporary directory')
        self.upload(__file__, self.remote + '/check.py')
        for label in (self.a.sizes if self.a.only != 'encode' else []):
            width, height = SIZES[label]
            for codec in self.a.codecs:
                encoder, opts = CODECS[codec]
                tag = codec + '-' + label
                print('decode ' + tag, file=sys.stderr, flush=True)
                clip = self.out / (tag + '.mkv')
                if self.a.input_dir:
                    old = json.loads((self.a.input_dir / 'result.json').read_text())
                    meta = next(i for i in old['inputs'] if i['codec'] == codec and i['size'] == label)
                    src = self.a.input_dir / clip.name
                    if sha(src) != meta['sha256']:
                        raise RuntimeError('reused input hash mismatch')
                    shutil.copyfile(src, clip)
                else:
                    self.ff(['-f', 'lavfi', '-i', f'testsrc2=size={width}x{height}:rate=30', '-frames:v', '150',
                         '-an', '-pix_fmt', 'yuv420p', '-c:v', encoder, '-threads', '4', '-g', '30'] + opts + [str(clip)], 'generate-' + tag)
                reference = self.out / (tag + '.framemd5')
                self.ff(['-i', str(clip), '-map', '0:v:0', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough',
                         '-f', 'framemd5', str(reference)], 'reference-' + tag)
                md5s = [line.split(',')[-1].strip() for line in reference.read_text().splitlines() if line and not line.startswith('#')]
                metadata = {'codec': codec, 'size': label, 'width': width, 'height': height, 'sha256': sha(clip),
                            'reference_sha256': sha(reference), 'probe': self.probe(clip, 'probe-' + tag)}
                self.result['inputs'].append(metadata)
                self.upload(clip, self.remote + '/clip.mkv')
                common = dict(width=width, height=height, clip=self.remote + '/clip.mkv')
                decoded = self.pipeline('decode', tag + '-decode', raw=self.remote + '/decoded.i420', **common)
                actual = [x['md5'] for x in decoded.get('frames', [])]
                matched = sum(a == b for a, b in zip(actual, md5s))
                row = {'codec': codec, 'size': label, 'status': 'FAIL', 'decoded': decoded,
                       'expected_frames': len(md5s), 'matching_frames': matched,
                       'mismatched_indices': [i for i, (a, b) in enumerate(zip(actual, md5s)) if a != b]}
                if decoded['status'] == 'PASS':
                    if matched != 150 and len(actual) == len(md5s) == 150:
                        localraw = self.out / 'decoded.i420'
                        self.download('decoded.i420', localraw)
                        row['psnr_db'] = self.psnr(localraw, clip, width, height, tag + '-psnr')
                        localraw.unlink()
                    bench = self.pipeline('bench', tag + '-bench', **common)
                    player = self.pipeline('player', tag + '-player', **common)
                    row.update(benchmark=bench, player=player)
                    hardware = 'v4l2' + codec + 'dec'
                    row['status'] = 'PASS' if (matched == 150 and all(
                        r['status'] == 'PASS' and r['count'] == 150 and hardware in r['elements']
                        for r in (decoded, bench, player))) else 'FAIL'
                self.result['decode'].append(row)
                self.remote_run('rm -f ' + shlex.quote(self.remote) + '/decoded.i420 ' + shlex.quote(self.remote) + '/clip.mkv', 'remove-' + tag)
                save(self.out / 'result.json', self.result)
        for label in (self.a.sizes if self.a.only != 'decode' else []):
            width, height = SIZES[label]
            raw = self.out / 'source.i420'
            source = self.pipeline('source', 'source-' + label, width=width, height=height, raw=self.remote + '/source.i420')
            if source['status'] != 'PASS' or source['count'] != 150:
                raise RuntimeError('source generation failed')
            self.download('source.i420', raw)
            self.remote_run('rm -f ' + shlex.quote(self.remote) + '/source.i420', 'remove-source-' + label)
            for codec in ('h264', 'h265'):
                tag = codec + '-' + label + '-encode'
                print('encode ' + tag, file=sys.stderr, flush=True)
                bitrate = 8_000_000 if label == '1080p' else 24_000_000
                enc = self.pipeline('encode', tag, width=width, height=height, codec=codec, bitrate=bitrate, encoded=self.remote + '/encoded.mkv')
                row = {'codec': codec, 'size': label, 'status': 'FAIL', 'target_bitrate': bitrate,
                       'pipeline': enc, 'source_sha256': sha(raw)}
                if enc['status'] == 'PASS':
                    encoded = self.out / (tag + '.mkv')
                    self.download('encoded.mkv', encoded)
                    row['sha256'] = sha(encoded)
                    row['probe'] = self.probe(encoded, 'probe-' + tag)
                    row['container_bitrate'] = int(row['probe']['format']['bit_rate'])
                    row['psnr_db'] = self.psnr(raw, encoded, width, height, tag + '-psnr')
                    row['status'] = 'PASS' if (int(row['probe']['streams'][0].get('nb_read_frames', '0')) == 150
                                              and row['psnr_db'] and float(row['psnr_db']) >= 30) else 'FAIL'
                self.result['encode'].append(row)
                save(self.out / 'result.json', self.result)
            raw.unlink()
        _, after, _ = self.remote_run('cat /proc/sys/kernel/random/boot_id; systemctl show piano-kbd-monitor.service bluetooth.service -p Id -p MainPID -p ActiveState', 'identity-after')
        self.result['same_boot'] = after.splitlines()[0] in before
        self.result['protected_services_unchanged'] = '\n'.join(after.splitlines()[1:]).strip() in before
        self.result['status'] = 'PASS' if (all(r['status'] == 'PASS' for r in self.result['decode'] + self.result['encode'])
                                        and self.result['same_boot'] and self.result['protected_services_unchanged']) else 'FAIL'

    def finish(self):
        if self.password:
            try:
                self.remote_run("sudo -S -p '' dmesg", 'dmesg-after', data=self.password, required=False)
            except Exception as e:
                self.result['dmesg_after_error'] = str(e)
            finally:
                self.password = None
        for name in ('source.i420', 'decoded.i420'):
            (self.out / name).unlink(missing_ok=True)
        if self.remote:
            try:
                self.remote_run('rm -rf -- ' + shlex.quote(self.remote), 'cleanup')
                self.result['remote_temporary_files_removed'] = True
            except Exception as e:
                self.result.update(status='FAIL', cleanup_error=str(e),
                                   remote_temporary_files_removed=False)
        save(self.out / 'result.json', self.result)
        print(json.dumps({'status': self.result['status'], 'schema': self.result['schema'],
                          'result_file': str(self.out / 'result.json')}))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        return worker(json.loads(Path(sys.argv[2]).read_text()))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ssh', required=True, help='user@host, using existing SSH host keys and public-key auth')
    ap.add_argument('--serial', required=True, help='expected androidboot.serialno')
    ap.add_argument('--kernel', required=True, help='expected uname -r')
    ap.add_argument('--output', required=True, type=Path, help='new private results directory')
    ap.add_argument('--ffmpeg', default='ffmpeg')
    ap.add_argument('--ffprobe', default='ffprobe')
    ap.add_argument('--sudo-password-stdin', action='store_true')
    ap.add_argument('--gst-debug', default='v4l2*:4,decodebin3:4', help='target logging; verbose logs affect performance')
    ap.add_argument('--input-dir', type=Path, help='reuse generated clips, verifying hashes against result.json')
    ap.add_argument('--only', choices=('all', 'decode', 'encode'), default='all')
    ap.add_argument('--codecs', nargs='+', choices=CODECS, default=list(CODECS))
    ap.add_argument('--sizes', nargs='+', choices=SIZES, default=list(SIZES))
    a = ap.parse_args()
    check = Check(a)
    try:
        check.execute()
    except (Exception, KeyboardInterrupt) as e:
        check.result['error'] = str(e)
        check.result['status'] = 'FAIL'
        print(str(e), file=sys.stderr)
    finally:
        check.finish()
    return 0 if check.result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
