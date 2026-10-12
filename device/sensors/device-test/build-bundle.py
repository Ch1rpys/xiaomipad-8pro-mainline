#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build pinned upstream Meson projects and assemble a relocatable ARM64 test.

Requires the same ARM64 sysroot/cross file and native Meson/protoc tools used
by the sensor reference builds. No package installation or device access.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hexagonrpc-source', type=Path, required=True)
    p.add_argument('--libssc-source', type=Path, required=True)
    p.add_argument('--cross-file', type=Path, required=True)
    p.add_argument('--sysroot', type=Path, required=True)
    p.add_argument('--build', type=Path, required=True, help='new build directory')
    p.add_argument('--output', type=Path, required=True, help='new bundle directory')
    p.add_argument('--private-input', type=Path, required=True, help='directory containing hexagonfs/ from this tablet; copied only into local output')
    args = p.parse_args()
    here = Path(__file__).resolve().parent
    public = here.parents[2]
    build, out, sysroot = args.build.resolve(), args.output.resolve(), args.sysroot.resolve()
    build.mkdir(parents=True, exist_ok=False)
    out.mkdir(parents=True, exist_ok=False)
    receipt = {'state': 'OFFLINE_BUILD_ONLY', 'device_access': False, 'sources': {},
               'cross_file_sha256': sha(args.cross_file), 'tools': {}, 'runtime_origin': {}}
    for tool, flag in [('meson', '--version'), ('aarch64-linux-gnu-gcc', '--version'), ('qemu-aarch64-static', '--version')]:
        receipt['tools'][tool] = subprocess.check_output([tool, flag], text=True).splitlines()[0]
    for name, repo in [('hexagonrpc', args.hexagonrpc_source), ('libssc', args.libssc_source)]:
        lockfile = here.parent/name/'source.json'
        lock = json.loads(lockfile.read_text())
        source = build/(name+'-source'); source.mkdir()
        archive = subprocess.check_output(['git', '-C', str(repo), 'archive', lock['commit']])
        with tarfile.open(fileobj=io.BytesIO(archive)) as t:
            t.extractall(source, filter='data')
        # git apply from a subdirectory of another repository may silently skip
        # paths. Give the extracted source its own repository before applying.
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        for patch in lock['patches']:
            f = lockfile.parent/patch['path']
            if sha(f) != patch['sha256']:
                raise ValueError('patch hash mismatch: ' + str(f))
            subprocess.run(['git', '-C', str(source), 'apply', '--check', '--whitespace=error-all', str(f)], check=True)
            subprocess.run(['git', '-C', str(source), 'apply', str(f)], check=True)
        dest = build/(name+'-build')
        command = ['meson', 'setup', str(dest), str(source), '--cross-file', str(args.cross_file.resolve()),
                   '--prefix=/usr', '--libdir=lib/aarch64-linux-gnu', '--buildtype=release']
        if name == 'hexagonrpc':
            command.append('-Dhexagonrpcd_verbose=true')
        with (build/(name+'.log')).open('wb') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
            subprocess.run(['meson', 'compile', '-C', str(dest)], check=True, stdout=log, stderr=subprocess.STDOUT)
            if name == 'hexagonrpc':
                subprocess.run(['meson', 'test', '-C', str(dest), '--print-errorlogs'], check=True, stdout=log, stderr=subprocess.STDOUT)
        receipt['sources'][name] = lock
    (out/'bin').mkdir(); (out/'lib').mkdir()
    inputs = [build/'hexagonrpc-build/hexagonrpcd/hexagonrpcd', build/'libssc-build/src/ssccli']
    for f in inputs:
        shutil.copyfile(f, out/'bin'/f.name); (out/'bin'/f.name).chmod(0o755)
    search = [build/'hexagonrpc-build/libhexagonrpc', build/'libssc-build/src',
              sysroot/'usr/lib/aarch64-linux-gnu', sysroot/'lib/aarch64-linux-gnu']
    pending = inputs + [sysroot/'usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1']
    copied = set()
    while pending:
        f = pending.pop()
        elf = subprocess.check_output(['aarch64-linux-gnu-readelf', '-h', '-d', str(f)], text=True)
        if 'AArch64' not in elf:
            raise ValueError('non-ARM64 input: ' + str(f))
        if f not in inputs:
            shutil.copyfile(f.resolve(), out/'lib'/f.name)
            (out/'lib'/f.name).chmod(0o755)
            receipt['runtime_origin'][f.name] = str(f.relative_to(sysroot)) if sysroot in f.parents else f.name
        for name in re.findall(r'\(NEEDED\).*\[(.*?)\]', elf):
            if name in copied:
                continue
            found = next((d/name for d in search if (d/name).is_file()), None)
            if found is None:
                raise FileNotFoundError('missing runtime library: ' + name)
            copied.add(name); pending.append(found)
    for name in ('run.sh', 'run.py', 'qrtr-lookup.py', 'README.zh-CN.md'):
        shutil.copyfile(here/name, out/name)
    shutil.copyfile(here.parent/'qrtr.py', out/'qrtr.py')
    (out/'run.sh').chmod(0o755)
    shutil.copytree(args.private_input, out/'private-input')
    # No links to original private inputs or host sysroot are allowed in output.
    if any(f.is_symlink() for f in out.rglob('*')):
        raise ValueError('bundle contains symlinks')
    shutil.copytree(public/'LICENSES', out/'LICENSES')
    shutil.copyfile(public/'NOTICE', out/'NOTICE')
    # Include distribution library copyright notices without installing packages.
    for f in (sysroot/'usr/share/doc').glob('*/copyright'):
        dest = out/'LICENSES/runtime'/f.parent.name
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(f, dest)
    receipt['sha256'] = {str(f.relative_to(out)): sha(f) for f in sorted(out.rglob('*')) if f.is_file()}
    (out/'payload.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
