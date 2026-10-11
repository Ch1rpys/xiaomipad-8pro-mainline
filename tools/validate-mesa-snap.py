#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check gpu-2404 layout/ELFs and softpipe pixels in a fresh core24 userspace.

No snap daemon, GPU device, display, confinement or hardware acceptance.
The SDK is used only to compile mesa/egl-smoke.c; runtime has no SDK packages.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_root', REPO / 'tools/lib/build_root.py')
roots = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roots)


def run(command):
    return subprocess.check_output(list(map(str, command)), text=True, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, LC_ALL="C"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', type=Path, required=True)
    ap.add_argument('--sdk-root', type=Path, required=True)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--consumer', type=Path, action='append', default=[], help='Frozen consumer .snap (repeatable)')
    ap.add_argument('--core24', type=Path, help='Also compare the actual core24 snap libc ABI')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pins = json.loads((REPO / 'mesa/snap/core24-sdk.json').read_text())
    assert roots.sha256(args.base) == pins['build_root']['sha256']
    manifest = json.loads((args.build / 'manifest.json').read_text())
    snap = (args.build / manifest['package']['file']).resolve()
    assert roots.sha256(snap) == manifest['package']['sha256']
    assert manifest['source'] == json.loads((REPO / 'mesa/source.json').read_text())
    (out / 'squashfs.txt').write_text(run(['unsquashfs', '-s', snap]))
    metadata = json.loads(run(['unsquashfs', '-cat', snap, 'meta/snap.yaml']))
    assert metadata['name'] == 'piano-mesa-2404' and metadata['base'] == 'core24'
    assert metadata['architectures'] == ['arm64'] and metadata['confinement'] == 'strict'
    assert metadata['slots'] == {'gpu-2404': {'interface': 'content', 'content': 'gpu-2404', 'read': ['$SNAP']}}
    (out / 'snap.json').write_text(json.dumps(metadata, indent=2)+'\n')
    root = out / 'runtime'
    root.mkdir()
    with tarfile.open(args.base) as tar:
        tar.extractall(root, members=[m for m in tar.getmembers()
                       if not m.isdev() and not m.name.lstrip('./').startswith('dev/')],
                       filter='fully_trusted')
    provider = root / 'test/provider'
    provider.parent.mkdir()
    (out / 'unpack.log').write_text(run(['unsquashfs', '-no-progress', '-d', provider, snap]))
    required = ['bin/gpu-2404-provider-wrapper', 'libdrm', 'drirc.d', 'X11/locale', 'X11/XErrorDB']
    assert all((provider / p).exists() for p in required)
    assert os.access(provider / required[0], os.X_OK)
    consumers = {}
    for consumer in args.consumer:
        text = run(['unsquashfs', '-cat', consumer, 'meta/snap.yaml'])
        (out / (consumer.name + '.yaml')).write_text(text)
        assert 'base: core24' in text and 'target: $SNAP/gpu-2404' in text
        paths = re.findall(r'(?:bind|symlink): \$SNAP/gpu-2404/(\S+)', text)
        assert paths and all((provider / p).exists() for p in paths), paths
        consumers[consumer.name] = {'sha256': roots.sha256(consumer), 'layout': paths}
    # Compile against the core24 SDK; no SDK package is added to the clean runtime.
    sdk = args.sdk_root.resolve()
    shutil.copyfile(REPO / 'mesa/egl-smoke.c', sdk / 'tmp/piano-egl-smoke.c')
    roots.chroot(sdk, 'gcc -O2 -o /tmp/piano-egl-smoke /tmp/piano-egl-smoke.c -lEGL -lGLESv2', log=out / 'compile.log')
    shutil.copyfile(sdk / 'tmp/piano-egl-smoke', root / 'test/piano-egl-smoke')
    (root / 'test/piano-egl-smoke').chmod(0o755)
    shutil.copyfile(root / 'test/piano-egl-smoke', out / 'piano-egl-smoke')
    (out / 'piano-egl-smoke').chmod(0o755)
    for node in ('null', 'random', 'urandom'):
        (root / 'dev').mkdir(exist_ok=True)
        (root / 'dev' / node).touch()
    (root / 'tmp/runtime').mkdir(mode=0o700)
    # Bind only these three non-GPU devices, with a private network namespace.
    wrapper = ('set -eu; for node in null random urandom; do '
               'mount --bind /dev/$node "$1/dev/$node"; done; '
               'mount -t proc proc "$1/proc"; root=$1; shift; '
               'exec chroot "$root" /usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C '
               'XDG_RUNTIME_DIR=/tmp/runtime "$@"')
    prefix = ['timeout', '-k', '5', '120', 'unshare', '--map-root-user', '--mount', '--net',
              '--pid', '--fork', '--kill-child', 'sh', '-c', wrapper, 'sh', str(root),
              '/test/provider/bin/gpu-2404-provider-wrapper']
    log = run([*prefix, '/usr/bin/env', 'LIBGL_ALWAYS_SOFTWARE=1', 'GALLIUM_DRIVER=softpipe',
               '/test/piano-egl-smoke', 'softpipe'])
    (out / 'softpipe.log').write_text(log)
    assert 'renderer=softpipe' in log and 'render_readback=PASS' in log
    negative = subprocess.run([*prefix, '/usr/bin/env', 'LIBGL_ALWAYS_SOFTWARE=1', 'GALLIUM_DRIVER=softpipe',
                               '/test/piano-egl-smoke', 'Adreno'], capture_output=True, text=True)
    (out / 'hardware-negative.log').write_text(negative.stdout + negative.stderr)
    assert negative.returncode != 0 and 'Required renderer missing' in negative.stderr
    elves, highest, needed_glibc = {}, (0, 0), set()
    libs = provider / 'usr/lib/aarch64-linux-gnu'
    for path in sorted(libs.rglob('*')):
        if not path.is_file() or path.is_symlink() or path.read_bytes()[:4] != b'\x7fELF':
            continue
        assert path.name not in ('libc.so.6', 'libm.so.6', 'ld-linux-aarch64.so.1')
        assert 'AArch64' in run(['readelf', '-h', path])
        dynamic = run(['readelf', '-d', path])
        assert 'RPATH' not in dynamic and 'RUNPATH' not in dynamic
        versions = run(['readelf', '--version-info', path]).split('Version needs section', 1)[-1]
        glibc = [tuple(map(int, v.split('.'))) for v in re.findall(r'Name: GLIBC_([0-9.]+)', versions)]
        needed_glibc.update(re.findall(r'Name: (GLIBC_[\w.]+)', versions))
        assert 'GLIBC_PRIVATE' not in versions
        highest = max([highest, *glibc])
        relative = str(path.relative_to(root))
        deps = run([*prefix, '/usr/bin/ldd', '/' + relative])
        assert 'not found' not in deps and '/build/' not in deps
        elves[str(path.relative_to(provider))] = {'sha256': roots.sha256(path), 'dependencies': deps,
                                                  'max_glibc': '.'.join(map(str, max(glibc, default=(0, 0))))}
    libc = root / 'usr/lib/aarch64-linux-gnu/libc.so.6'
    provided = max(tuple(map(int, v.split('.'))) for v in re.findall(
        r'Name: GLIBC_([0-9.]+)', run(['readelf', '--version-info', libc])))
    assert highest <= provided
    core24 = None
    if args.core24:
        core_libc = out / 'core24-libc.so.6'
        core_libc.write_bytes(subprocess.check_output(['unsquashfs', '-cat', str(args.core24),
                                                       'usr/lib/aarch64-linux-gnu/libc.so.6']))
        assert 'AArch64' in run(['readelf', '-h', core_libc])
        actual = set(re.findall(r'Name: (GLIBC_[\w.]+)', run(['readelf', '--version-info', core_libc])))
        assert needed_glibc <= actual, sorted(needed_glibc - actual)
        core24 = {'snap_sha256': roots.sha256(args.core24), 'libc_sha256': roots.sha256(core_libc),
                  'required_versions': sorted(needed_glibc), 'all_required_versions_provided': True}
    assert elves
    for folder in ('usr/share/glvnd/egl_vendor.d', 'usr/share/vulkan/icd.d'):
        for path in (provider / folder).glob('*.json'):
            name = json.loads(path.read_text())['ICD']['library_path']
            assert name == Path(name).name and (libs / name).exists()
    (out / 'elf-layout.json').write_text(json.dumps(elves, indent=2)+'\n')
    report = {'status': 'OFFLINE_SOFTWARE_ONLY_PASS', 'package': {**manifest['package'], 'bytes': snap.stat().st_size},
              'base': pins['build_root'], 'core24': core24, 'metadata': metadata, 'consumers': consumers,
              'elf_count': len(elves), 'max_glibc_required': '.'.join(map(str, highest)),
              'runtime_glibc_provided': '.'.join(map(str, provided)), 'layout': required,
              'software_renderer': 'softpipe', 'hardware_required_negative': negative.returncode,
              'probe_sha256': roots.sha256(out / 'piano-egl-smoke'),
              'not_verified': ['snap install/connect', 'snap confinement/AppArmor', 'A830 rendering', 'snap-store output']}
    (out / 'validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
