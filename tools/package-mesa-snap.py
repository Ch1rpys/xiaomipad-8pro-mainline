#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Adapted for piano, 2026-10-11; see mesa/snap/provenance.json.
"""Package a fresh core24 Mesa build as a gpu-2404 content provider.

Runs inside the pinned ARM64 SDK. Runtime libraries come from this build and
the SDK's signed Ubuntu snapshot; libc and its loader stay with core24.
This does not install, connect or publish a snap.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
LIB = Path('usr/lib/aarch64-linux-gnu')
APIS = ('libEGL.so.1', 'libGL.so.1', 'libOpenGL.so.0', 'libGLESv2.so.2', 'libvulkan.so.1')
CORE = {'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'librt.so.1', 'libdl.so.2',
        'libresolv.so.2', 'libutil.so.1', 'ld-linux-aarch64.so.1'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dependencies(path, libdir):
    result = subprocess.run(['ldd', str(path)], text=True, capture_output=True,
                            env=dict(os.environ, LC_ALL='C', LD_LIBRARY_PATH=str(libdir)))
    if result.returncode or 'not found' in result.stdout:
        raise RuntimeError(f'unresolved library: {path}\n{result.stdout}{result.stderr}')
    return [Path(value) for value in re.findall(r'=> (/\S+) \(', result.stdout)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-output', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.machine() not in ('aarch64', 'arm64'):
        parser.error('run this packager inside the ARM64 core24 SDK')
    os_release = Path('/etc/os-release').read_text()
    if not re.search(r'^VERSION_ID="24\.04"$', os_release, re.M):
        parser.error('core24 content must be built against Ubuntu 24.04, not the host desktop ABI')
    build = args.build_output.resolve()
    result = json.loads((build / 'build-result.json').read_text())
    identity = json.loads((build / 'input.json').read_text())
    source = json.loads((REPO / 'mesa/source.json').read_text())
    if (result['profile'] != 'gpu-2404' or result['prefix'] != '/usr'
            or result['input_sha256'] != sha(build / 'input.json') or identity['source'] != source):
        parser.error('incompatible or unverified build')
    stage = build / 'stage'
    for name, digest in result['files_sha256'].items():
        if sha(stage / name) != digest:
            parser.error('changed build file: ' + name)
    for name, target in result['symlinks'].items():
        if os.readlink(stage / name) != target:
            parser.error('changed build symlink: ' + name)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    recipe = REPO / 'packaging/mesa-snap'
    epoch = (build / 'source-date-epoch').read_text().strip()
    with tempfile.TemporaryDirectory(prefix='mesa-snap-') as temp:
        root = Path(temp) / 'prime'
        (root / LIB).mkdir(parents=True)
        for name in sorted(set(result['files_sha256']) | set(result['symlinks'])):
            rel = Path(name)
            if not (rel.is_relative_to(LIB) and '.so' in rel.name
                    or name.startswith(('usr/share/glvnd/', 'usr/share/vulkan/icd.d/', 'usr/share/drirc.d/'))):
                continue
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if name in result['symlinks']:
                dst.symlink_to(result['symlinks'][name])
            else:
                shutil.copy2(stage / rel, dst)

        # Mesa supplies the vendor implementations; GLVND and the Vulkan
        # loader supply the standard client entry points.
        queue = [p for p in (stage / LIB).rglob('*.so*') if p.is_file() and not p.is_symlink()]
        queue += [Path('/') / LIB / name for name in APIS]
        seen, sdk_files = set(), {}
        while queue:
            path = queue.pop()
            real = path.resolve(strict=True)
            if path.name in CORE or real in seen:
                continue
            seen.add(real)
            if not real.is_relative_to(stage):
                dst = root / LIB / path.name
                if dst.exists() and sha(dst) != sha(real):
                    raise RuntimeError('library name collision: ' + path.name)
                shutil.copy2(real, dst)
                sdk_files[path.name] = {'sha256': sha(real), 'sdk_path': str(path)}
            queue.extend(dependencies(real, stage / LIB))

        # Content can be mounted at any consumer path. The loader resolves
        # these sonames through the provider wrapper's library search path.
        for folder in ('usr/share/glvnd/egl_vendor.d', 'usr/share/vulkan/icd.d'):
            for manifest in (root / folder).glob('*.json'):
                data = json.loads(manifest.read_text())
                data['ICD']['library_path'] = Path(data['ICD']['library_path']).name
                manifest.write_text(json.dumps(data, indent=2) + '\n')
        (root / 'usr/share/drirc.d').rename(root / 'drirc.d')
        # gpu-2404 consumers bind these paths in their mount namespace even
        # when their current renderer does not use the corresponding data.
        runtime_data = {}
        for original, destination in (('/usr/share/libdrm', 'libdrm'),
                                      ('/usr/share/X11/locale', 'X11/locale')):
            shutil.copytree(original, root / destination)
        shutil.copy2('/usr/share/X11/XErrorDB', root / 'X11/XErrorDB')
        for folder in ('libdrm', 'X11'):
            for path in sorted((root / folder).rglob('*')):
                if path.is_file():
                    runtime_data[str(path.relative_to(root))] = sha(path)
        (root / 'bin').mkdir()
        shutil.copy2(recipe / 'gpu-2404-provider-wrapper', root / 'bin/gpu-2404-provider-wrapper')
        (root / 'bin/gpu-2404-provider-wrapper').chmod(0o755)
        docs = root / 'usr/share/doc/piano-mesa-2404'
        docs.mkdir(parents=True)
        shutil.copy2(build / ('mesa-' + source['version']) / 'docs/license.rst', docs / 'mesa-license.rst')
        shutil.copy2(REPO / 'LICENSES/oneplus-mesa-tools-GPL-2.0-only.txt', docs / 'packaging-license')
        for package in ('libdrm-common', 'libx11-data'):
            shutil.copy2(Path('/usr/share/doc') / package / 'copyright', docs / (package + '.copyright'))
        # Retain upstream notices for the SDK-provided dependency closure.
        for path in sorted(sdk_files):
            original = Path(sdk_files[path]['sdk_path'])
            owners = subprocess.run(['dpkg-query', '-S', str(original), str(original.resolve())],
                                    capture_output=True, text=True)
            packages = sorted(set(re.findall(r'^([^ :]+)(?::arm64)?: /', owners.stdout, re.M)))
            if not packages:
                raise RuntimeError('no package provenance for ' + str(original))
            sdk_files[path]['packages'] = packages
            for package in packages:
                copyright_file = Path('/usr/share/doc') / package / 'copyright'
                if copyright_file.exists():
                    shutil.copy2(copyright_file.resolve(), docs / (package + '.copyright'))
        provenance = {'source': source, 'build': result, 'runtime_libraries': sdk_files,
                      'runtime_data_sha256': runtime_data,
                      'recipe_sha256': {str(p.relative_to(REPO)): sha(p) for p in
                                        [Path(__file__), recipe / 'VERSION', recipe / 'gpu-2404-provider-wrapper']}}
        if (build / 'native-generator.json').exists():
            provenance['native_generator'] = json.loads((build / 'native-generator.json').read_text())
        fingerprint = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:8]
        version = source['version'] + '+piano' + (recipe / 'VERSION').read_text().strip() + '.' + fingerprint
        metadata = {'name': 'piano-mesa-2404', 'version': version, 'base': 'core24',
                    'summary': 'Adreno 830 graphics for gpu-2404 consumers',
                    'description': 'Development Freedreno and Turnip content provider, with softpipe GL fallback. Hardware acceptance is pending.',
                    'architectures': ['arm64'], 'grade': 'devel', 'confinement': 'strict',
                    'slots': {'gpu-2404': {'interface': 'content', 'content': 'gpu-2404', 'read': ['$SNAP']}}}
        (root / 'meta').mkdir()
        (root / 'meta/snap.yaml').write_text(json.dumps(metadata, indent=2) + '\n')
        (docs / 'build.json').write_text(json.dumps(provenance, indent=2) + '\n')
        snap = output / ('piano-mesa-2404_' + version + '_arm64.snap')
        subprocess.run(['mksquashfs', str(root), str(snap), '-noappend', '-all-root', '-no-xattrs',
                        '-comp', 'xz', '-processors', '4', '-mkfs-time', epoch, '-all-time', epoch],
                       check=True, env={k: v for k, v in os.environ.items() if k != 'SOURCE_DATE_EPOCH'})
        provenance.update(version=version, package={'file': snap.name, 'sha256': sha(snap)})
        (output / 'manifest.json').write_text(json.dumps(provenance, indent=2) + '\n')
        print(json.dumps(provenance['package']))


if __name__ == '__main__':
    main()
