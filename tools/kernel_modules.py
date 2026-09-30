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

