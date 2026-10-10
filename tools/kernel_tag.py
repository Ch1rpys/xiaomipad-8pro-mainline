#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Print the upstream kernel tag a kernel commit is based on: kernel_tag.py SOURCE [COMMIT].

The tag is derived from VERSION/PATCHLEVEL/SUBLEVEL/EXTRAVERSION in the commit's top-level
Makefile, the version Kbuild itself uses, and must exist and be reachable from the commit.
Nearest-tag search (git describe --match 'v[0-9]*') is not used: project tags on the kernel
repository such as v0.1.0-preview also start with v and a digit.
"""
import re
import subprocess
import sys

FIELDS = ('VERSION', 'PATCHLEVEL', 'SUBLEVEL', 'EXTRAVERSION')


def makefile_tag(makefile):
    """Return the upstream tag name (v7.2.6, v7.2, v7.3-rc1) for a top-level kernel Makefile."""
    values = {}
    for line in makefile.splitlines():
        match = re.fullmatch(r'(' + '|'.join(FIELDS) + r') *= *(.*?) *', line)
        if match and match[1] not in values:
            values[match[1]] = match[2]
        if len(values) == len(FIELDS):
            break
    if (len(values) != len(FIELDS)
            or not all(re.fullmatch(r'0|[1-9][0-9]*', values[n]) for n in FIELDS[:3])
            or not re.fullmatch(r'(-rc[1-9][0-9]*)?', values['EXTRAVERSION'])):
        raise ValueError(f'Not a kernel version in the top-level Makefile: {values}')
    tag = f'v{values["VERSION"]}.{values["PATCHLEVEL"]}'
    if values['SUBLEVEL'] != '0':
        tag += f'.{values["SUBLEVEL"]}'
    return tag + values['EXTRAVERSION']


def upstream_tag(source, commit='HEAD'):
    def git(*words, check=True):
        return subprocess.run(['git', '-C', str(source), *words], capture_output=True, text=True, check=check)
    tag = makefile_tag(git('show', f'{commit}:Makefile').stdout)
    if git('rev-parse', '--verify', '--quiet', f'refs/tags/{tag}^{{commit}}', check=False).returncode:
        raise ValueError(f'Upstream tag {tag} named by the Makefile is missing; fetch the upstream tags')
    if git('merge-base', '--is-ancestor', f'refs/tags/{tag}', commit, check=False).returncode:
        raise ValueError(f'{commit} does not contain the upstream tag {tag} named by its Makefile')
    return tag


if __name__ == '__main__':
    if not 2 <= len(sys.argv) <= 3:
        raise SystemExit(__doc__.splitlines()[0])
    try:
        print(upstream_tag(*sys.argv[1:]))
    except (ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(getattr(error, 'stderr', None) or str(error))
