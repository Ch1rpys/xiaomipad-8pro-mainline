# SPDX-License-Identifier: GPL-2.0-only
"""Validate a Kbuild module staging receipt, independent of package format."""
import hashlib
from pathlib import PurePosixPath
import re
import subprocess


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_modules(kout, build, release):
    """Consume the Kbuild/depmod staging receipt; never rebuild or guess modules."""
    receipt = build.get('modules')
    if receipt is None:
        if (kout / 'modules.order').exists():
            raise ValueError('Modules were built but no verified staging receipt is present')
        return {}
    expected_root = f'modules-root/lib/modules/{release}'
    if receipt['kernel_release'] != release or receipt['root'] != expected_root:
        raise ValueError('Module release or staging root differs from the Image')
    root = kout / expected_root
    paths = sorted(root.rglob('*'))
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in paths):
        raise ValueError('Unexpected module staging entry')
    files = {str(p.relative_to(root)): p for p in paths if p.is_file()}
    if set(files) != set(receipt['files']) or not {'modules.dep', 'modules.alias', 'modules.builtin'} <= files.keys():
        raise ValueError('Module staging file set differs from its receipt')
    for name, digest in receipt['files'].items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or sha(files[name]) != digest:
            raise ValueError(f'Module staging hash/path mismatch: {name}')
    modules = [p for n, p in files.items() if re.fullmatch(r'.+\.ko(?:\.(?:gz|xz|zst))?', n)]
    if not modules or len(modules) != receipt['count']:
        raise ValueError('Module count differs from the staging receipt')
    vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic', *map(str, modules)], text=True).splitlines()
    if len(vermagic) != len(modules) or any(not line.startswith(release + ' ') for line in vermagic):
        raise ValueError('A staged module does not match the kernel release')
    return files



def subset_metadata(manifest):
    """Validate the plain subset format; return its safe module-name set."""
    if manifest.get('state') != 'OFFLINE_MODULE_SUBSET_NOT_LOADED':
        raise ValueError('Expected a staged module subset')
    release = manifest['kernel_release']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', release):
        raise ValueError('Invalid module release')
    for key, length in [('kernel_commit', 40), ('kernel_sha256', 64),
                        ('config_sha256', 64), ('build_result_sha256', 64)]:
        if not re.fullmatch('[0-9a-f]{' + str(length) + '}', manifest[key]):
            raise ValueError(f'Invalid module identity: {key}')
    for key in ('requested', 'forbidden', 'builtins'):
        if not isinstance(manifest[key], list) or any(
                not isinstance(n, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_]*', n)
                for n in manifest[key]):
            raise ValueError(f'Invalid module names: {key}')
    if not manifest['requested']:
        raise ValueError('No requested modules')
    prefix = f'lib/modules/{release}/'
    names = set()
    files = manifest['files']
    for path, digest in files.items():
        if (not path.startswith(prefix) or
                not re.fullmatch(r'[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*', path) or
                any(p in ('.', '..') for p in PurePosixPath(path).parts) or
                not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise ValueError(f'Invalid module payload path/hash: {path}')
        if re.search(r'\.ko(?:\.(?:gz|xz|zst))?$', path):
            names.add(re.sub(r'\.ko(?:\.(?:gz|xz|zst))?$', '', path.rsplit('/', 1)[1]).replace('-', '_'))
    if (len(names) != manifest['module_count'] or
            not {prefix + p for p in ('modules.dep', 'modules.alias', 'modules.builtin',
                                      'modules.builtin.modinfo', 'modules.order')} <= files.keys()):
        raise ValueError('Module count or metadata file set is incomplete')
    if set(manifest['forbidden']) & (names | set(manifest['builtins']) | set(manifest['requested'])):
        raise ValueError('Forbidden module in payload')
    if not set(manifest['requested']) <= names | set(manifest['builtins']):
        raise ValueError('Requested module missing from payload')
    return names


def verified_subset(root):
    """Verify a stage-kernel-modules tree before another format consumes it."""
    import json
    manifest = json.loads((root / 'module-manifest.json').read_text())
    names = subset_metadata(manifest)
    paths = list(root.rglob('*'))
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in paths):
        raise ValueError('Non-regular module subset entry')
    files = {str(p.relative_to(root)): p for p in paths if p.is_file()}
    if set(files) != set(manifest['files']) | {'module-manifest.json'}:
        raise ValueError('Module subset file set differs from its manifest')
    for name, digest in manifest['files'].items():
        if sha(files[name]) != digest:
            raise ValueError(f'Module subset hash mismatch: {name}')
        if re.search(r'\.ko(?:\.(?:gz|xz|zst))?$', name):
            version = subprocess.check_output(['modinfo', '-F', 'vermagic', str(files[name])], text=True)
            module = subprocess.check_output(['modinfo', '-F', 'name', str(files[name])], text=True).strip()
            if not version.startswith(manifest['kernel_release'] + ' ') or module not in names:
                raise ValueError(f'Module subset ABI/name mismatch: {name}')
    return manifest


def runtime_metadata(manifest):
    """Deterministic BusyBox-readable checks and explicit-load policy for RAM diagnostics."""
    import json
    names = subset_metadata(manifest)
    metadata = {
        'etc/piano-modules.json': (json.dumps(manifest, indent=2) + '\n').encode(),
        'etc/piano-modules.release': (manifest['kernel_release'] + '\n').encode(),
        'etc/piano-modules.requested': ('\n'.join(manifest['requested']) + '\n').encode(),
        'etc/modprobe.d/piano-ram-modules.conf': (
            '# Temporary RAM diagnostic: load named modules explicitly after logging.\n' +
            ''.join('blacklist ' + n + '\n' for n in sorted(names))).encode(),
    }
    checks = dict(manifest['files'])
    checks.update({p: hashlib.sha256(data).hexdigest() for p, data in metadata.items()})
    metadata['etc/piano-modules.sha256'] = ''.join(f'{digest}  {path}\n' for path, digest in sorted(checks.items())).encode()
    return metadata
