#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create a new ext4 file from a pinned Ubuntu Desktop TAR without host root.

Uses the existing TAR merger and upstream mke2fs/libarchive, not a filesystem writer.
No block devices, tablet commands, mounts, package installation or accounts.
"""
import argparse
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import uuid


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tar', required=True, type=Path)
    parser.add_argument('--tar-sha256', required=True)
    parser.add_argument('--mke2fs', required=True, type=Path, help='Version with libarchive TAR support')
    parser.add_argument('--mke2fs-config', required=True, type=Path, help='Explicit upstream formatter configuration')
    parser.add_argument('--e2fsck', required=True, type=Path)
    parser.add_argument('--uuid', required=True, type=uuid.UUID, help='Filesystem image identity, not a partition UUID')
    parser.add_argument('--size-mib', type=int, default=12288)
    parser.add_argument('--output', required=True, type=Path, help='New output directory; never a block-device path')
    args = parser.parse_args()
    if not args.tar.is_file() or args.size_mib < 64 or sha(args.tar) != args.tar_sha256:
        parser.error('Need sufficient filesystem size and the exact input TAR hash')
    repo = Path(__file__).resolve().parent.parent
    merger_path = Path(__file__).with_name('merge-desktop-tars.py')
    spec = importlib.util.spec_from_file_location('desktop_merge', merger_path)
    merger = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(merger)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    image = out / 'ubuntu-root.ext4.partial'
    policy = out / 'image-policy.tar'
    profile = repo / 'ubuntu/26.04.sources'
    updates = {'etc/apt/sources.list.d/ubuntu.sources': profile.read_bytes(),
               'etc/cloud/cloud-init.disabled': b''}
    remove = 'etc/apt/sources.list.d/cdrom.sources'
    result = {'state': 'BUILDING', 'scope': 'Filesystem file only; no installed kernel or device boot claim',
              'input_tar_sha256': args.tar_sha256, 'profile_sha256': sha(profile),
              'builder_sha256': sha(Path(__file__)), 'merger_sha256': sha(merger_path),
              'mke2fs_sha256': sha(args.mke2fs), 'mke2fs_config_sha256': sha(args.mke2fs_config),
              'e2fsck_sha256': sha(args.e2fsck), 'filesystem_uuid': str(args.uuid),
              'filesystem_bytes': args.size_mib * 1024 * 1024,
              'policy': {'replace_or_add': sorted(updates), 'remove': [remove]},
              'account_created': False, 'packages_installed': False}

    def save():
        (out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')

    save()
    try:
        with tarfile.open(args.tar, 'r:') as base:
            root = base.getmember('.')
            if not root.isdir() or (root.uid, root.gid) != (0, 0):
                raise ValueError('Expected explicit root-owned archive root')
            epoch = int(root.mtime)
            parents = {'.'}
            for name in [*updates, remove]:
                parents.update(str(p) for p in PurePosixPath(name).parents)
            with tarfile.open(policy, 'w', format=tarfile.PAX_FORMAT) as upper:
                for name in sorted(parents):
                    member = copy.copy(base.getmember(name))
                    if not member.isdir():
                        raise ValueError(f'Policy parent is not an existing directory: {name}')
                    upper.addfile(member)
                for name, contents in updates.items():
                    member = tarfile.TarInfo(name)
                    member.uid = member.gid = 0
                    member.mode, member.mtime, member.size = 0o644, epoch, len(contents)
                    upper.addfile(member, io.BytesIO(contents))
                if not base.getmember(remove).isreg():
                    raise ValueError('Expected the original regular CDROM source file')
                whiteout = tarfile.TarInfo(remove)
                whiteout.type, whiteout.devmajor, whiteout.devminor = tarfile.CHRTYPE, 0, 0
                whiteout.mode, whiteout.mtime = 0o644, epoch
                upper.addfile(whiteout)
            with image.open('xb') as stream:
                stream.truncate(result['filesystem_bytes'])
            env = dict(os.environ, MKE2FS_CONFIG=str(args.mke2fs_config.resolve()),
                       E2FSPROGS_FAKE_TIME=str(epoch), LC_ALL='C.UTF-8', LANGUAGE='C')
            command = [str(args.mke2fs.resolve()), '-q', '-t', 'ext4', '-b', '4096', '-m', '0',
                       '-U', str(args.uuid), '-L', 'piano-root',
                       '-E', f'lazy_itable_init=0,lazy_journal_init=0,root_owner=0:0,hash_seed={args.uuid}',
                       '-d', '-', str(image)]
            result['command'], result['epoch'] = command, epoch
            save()
            print('Populating a new regular ext4 file from the TAR stream', flush=True)
            with (out / 'mke2fs.log').open('wb') as log:
                proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, env=env)
                try:
                    with tarfile.open(policy, 'r:') as upper, \
                            tarfile.open(fileobj=proc.stdin, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                        result['merge'] = merger.merge(base, upper, archive)
                    proc.stdin.close()
                    if proc.wait() != 0:
                        raise RuntimeError('mke2fs failed; inspect mke2fs.log')
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait()
            with (out / 'e2fsck.log').open('wb') as log:
                subprocess.run([str(args.e2fsck.resolve()), '-fn', str(image)],
                               stdout=log, stderr=subprocess.STDOUT, env=env, check=True)
        final = out / 'ubuntu-root.ext4'
        image.replace(final)
        result.update(state='EXT4_BUILT_FSCK_CLEAN_NOT_BOOTED', image_sha256=sha(final),
                      image_allocated_bytes=final.stat().st_blocks * 512, policy_tar_sha256=sha(policy))
    except Exception as exc:
        result.update(state='FAILED', error=str(exc))
        save()
        raise
    save()
    print(json.dumps({k: result[k] for k in ('state', 'image_sha256', 'filesystem_uuid', 'image_allocated_bytes')}, indent=2))


if __name__ == '__main__':
    main()
