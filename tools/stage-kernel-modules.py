#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Stage explicitly selected modules and their standard kmod dependencies.

No modules are loaded. The output is a plain root tree, usable by initramfs or
native package tooling. An Image/config/receipt lock binds it to the kernel.
"""
import argparse
import fcntl
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

from kernel_modules import sha, verified_modules


def module_name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', value):
        raise argparse.ArgumentTypeError('Use a module name, not a path or option')
    return value.replace('-', '_')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--module', type=module_name, action='append', default=[],
                        help='Explicit root module; repeat as needed (built-ins are accepted)')
    selection.add_argument('--all', action='store_true',
                           help='Carry the complete verified module tree for a disk-root RAM boot')
    parser.add_argument('--forbid-module', type=module_name, action='append', default=[],
                        help='Reject a root or dependency with this module name')
    args = parser.parse_args()
    kout = args.kernel_out.resolve()
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error('Output must not exist')
    if output.resolve().is_relative_to(kout):
        parser.error('Output must be outside the kernel build tree')
    requested = sorted(set(args.module))
    forbidden = set(args.forbid_module)
    if forbidden.intersection(requested):
        parser.error('A requested module is forbidden')
    output.parent.mkdir(parents=True, exist_ok=True)

    with (kout / '.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        build_file = kout / 'build-result.json'
        build = json.loads(build_file.read_text())
        release = (kout / 'include/config/kernel.release').read_text().strip()
        for name in ('arch/arm64/boot/Image', '.config'):
            if sha(kout / name) != build['files'][name]:
                raise ValueError(f'Kernel artifact differs from receipt: {name}')
        files = verified_modules(kout, build, release)
        if not files:
            raise ValueError('Build has no verified module payload')
        root = kout / build['modules']['root']
        selected = {}
        builtins = set()
        commands = {}
        if args.all:
            selected = {n: p for n, p in files.items() if re.search(r'\.ko(?:\.(?:gz|xz|zst))?$', n)}
            requested = sorted({re.sub(r'\.ko(?:\.(?:gz|xz|zst))?$', '', p.name).replace('-', '_')
                                for p in selected.values()})
            if forbidden.intersection(requested):
                raise ValueError('Forbidden module in complete tree')
        for name in (() if args.all else requested):
            # kmod owns dependency/softdep/built-in resolution. Ignore host config.
            result = subprocess.check_output([
                'modprobe', '--config', '/dev/null', '--dirname', str(kout / 'modules-root'),
                '--set-version', release, '--show-depends', name], text=True)
            commands[name] = []
            for line in result.splitlines():
                words = shlex.split(line)
                if len(words) == 2 and words[0] == 'builtin':
                    builtin = module_name(words[1])
                    if builtin in forbidden:
                        raise ValueError(f'Forbidden built-in dependency: {builtin}')
                    builtins.add(builtin)
                    commands[name].append({'builtin': builtin})
                elif len(words) == 2 and words[0] == 'insmod':
                    source = Path(words[1])
                    relative = str(source.relative_to(root))
                    if relative not in files or files[relative] != source:
                        raise ValueError(f'Unverified module dependency: {source}')
                    actual_name = subprocess.check_output(['modinfo', '-F', 'name', str(source)],
                                                          text=True).strip().replace('-', '_')
                    if actual_name in forbidden:
                        raise ValueError(f'Forbidden module dependency: {actual_name}')
                    selected[relative] = source
                    commands[name].append({'insmod': relative})
                else:
                    raise ValueError(f'Unexpected kmod dependency directive: {line}')

        with tempfile.TemporaryDirectory(prefix='.piano-modules-', dir=output.parent) as temporary:
            stage = Path(temporary) / 'root'
            destination = stage / 'lib/modules' / release
            destination.mkdir(parents=True)
            for name, source in selected.items():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                target.chmod(0o644)
                if sha(target) != build['modules']['files'][name]:
                    raise ValueError(f'Module changed during staging: {name}')
            for name in ('modules.builtin', 'modules.builtin.modinfo'):
                shutil.copyfile(root / name, destination / name)
            # Retain Kbuild order only for modules actually included in this tree.
            uncompressed = {re.sub(r'\.(gz|xz|zst)$', '', n) for n in selected}
            order = [n for n in (root / 'modules.order').read_text().splitlines() if n in uncompressed]
            (destination / 'modules.order').write_text(''.join(n + '\n' for n in order))
            subprocess.run(['depmod', '-b', str(stage), release], check=True)
            manifest = {
                'state': 'OFFLINE_MODULE_SUBSET_NOT_LOADED',
                'kernel_commit': build['kernel_commit'], 'kernel_release': release,
                'kernel_sha256': build['files']['arch/arm64/boot/Image'],
                'config_sha256': build['files']['.config'],
                'build_result_sha256': sha(build_file),
                'requested': requested, 'forbidden': sorted(forbidden),
                'builtins': sorted(builtins), 'module_count': len(selected),
                'kmod_version': subprocess.check_output(['modprobe', '--version'], text=True).strip(),
                'resolution': commands,
                'files': {str(p.relative_to(stage)): sha(p)
                          for p in sorted(stage.rglob('*')) if p.is_file()},
                'scope': 'Module files only; no firmware, autoload service, boot image or hardware test',
                'selection': 'all' if args.all else 'subset',
            }
            (stage / 'module-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            stage.rename(output)
    print(json.dumps({'output': str(output), 'module_count': len(selected),
                      'kernel_commit': build['kernel_commit']}, indent=2))


if __name__ == '__main__':
    main()
