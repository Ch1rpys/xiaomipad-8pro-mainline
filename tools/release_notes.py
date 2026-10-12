# SPDX-License-Identifier: MIT
"""Shared release-note rendering; attachment sizes are filled after packaging."""
from pathlib import Path
import re
import string

REPO = Path(__file__).resolve().parents[1]
REPO_URL = 'https://github.com/yzddmr6/xiaomipad-8pro-mainline'


def asset_prefix(version):
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]*', version):
        raise ValueError('release_name must be a filename-safe version')
    return f'piano-ubuntu-{version}'


def restore_commands(version, parts=None):
    prefix = asset_prefix(version)
    # The literal glob is convenient for normal releases. Numeric manifest order
    # also supports >10 parts, where shell glob order would put part10 before part2.
    inputs = ' '.join(parts) if parts and len(parts) > 10 else f'{prefix}-rootfs.img.zst.part*'
    return '\n'.join([
        'sha256sum -c SHA256SUMS.assets',
        *(f'unzip {prefix}-{kind}.zip' for kind in ('boot', 'tools', 'packages')),
        'mkdir -p rootfs',
        f'cat {inputs} | zstd -d > rootfs/root.sparse.img',
        'sha256sum -c SHA256SUMS',
    ])


def download_table(version, language, sizes=None):
    prefix = asset_prefix(version)
    zh = language == 'zh'
    purposes = (['启动镜像、发布清单及元数据', '切换与恢复工具', '升级用 deb 软件包',
                 '系统镜像；需下载全部分卷', '附件校验', '大小、内容与还原命令'] if zh else
                ['Boot images, release manifest and metadata', 'Switching and recovery tools',
                 'Deb packages for upgrades', 'System image; download every part',
                 'Attachment checksums', 'Sizes, contents and restore commands'])
    names = [f'{prefix}-{kind}.zip' for kind in ('boot', 'tools', 'packages')]
    names += [f'{prefix}-rootfs.img.zst.part*', 'SHA256SUMS.assets', 'assets-manifest.json']
    lines = ['| 文件名 | 大小 | 用途 |' if zh else '| File | Size | Purpose |', '|---|---:|---|']
    for name, purpose in zip(names, purposes):
        if sizes is None:
            size = '打包后填写' if zh else 'Pending packaging'
        elif name.endswith('*'):
            parts = [(n, s) for n, s in sizes.items() if n.startswith(name[:-1])]
            parts.sort(key=lambda pair: int(pair[0].rsplit('part', 1)[1]))
            size = '; '.join(f'{n.rsplit(".", 1)[1]}: {s:,} B' for n, s in parts)
        else:
            size = f'{sizes[name]:,} B'
        lines.append(f'| `{name}` | {size} | {purpose} |')
    return '\n'.join(lines)


def fill_asset_details(notes, version, sizes, parts):
    """Update only generated blocks, preserving handwritten Markdown verbatim."""
    for label, text in [('downloads-zh', download_table(version, 'zh', sizes)),
                        ('downloads-en', download_table(version, 'en', sizes)),
                        ('restore', '```sh\n' + restore_commands(version, parts) + '\n```')]:
        pattern = rf'(<!-- {label}:start -->\n).*?(\n<!-- {label}:end -->)'
        notes = re.sub(pattern, lambda m: m[1] + text + m[2], notes, flags=re.S)
    return notes


def render_notes(rootfs, stock_build, integration_commit, kernel_source, changes):
    version = rootfs['release_name']
    kernel_name = 'linux-image-' + rootfs['kernel_release']
    kernel = next(e for e in rootfs['packages'] if e['package'] == kernel_name)
    # Same pinned Ubuntu binary used by the maintenance initramfs builder.
    busybox = re.search(r'^package=busybox-static_(\S+)_arm64\.deb$',
                       (REPO / 'tools/fetch-busybox-arm64.sh').read_text(), re.M).group(1)
    return string.Template((REPO / 'packaging/release/RELEASE-NOTES.md.in').read_text()).substitute(
        release_name=version, prefix=asset_prefix(version), changes=changes,
        downloads_zh=download_table(version, 'zh'), downloads_en=download_table(version, 'en'),
        restore_commands=restore_commands(version), kernel_package=f'{kernel_name} {kernel["version"]}',
        stock_build=stock_build, apt_snapshot=rootfs['apt_snapshot'],
        repo_url=REPO_URL, integration_commit=integration_commit,
        integration_short=integration_commit[:7], kernel_url=kernel_source['url'],
        kernel_commit=kernel_source['commit'], kernel_short=kernel_source['commit'][:7],
        busybox_version=busybox)
