#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare a piano packaging DTB for the unchanged stock DTBO.

Uses the erhai packaging-only overlay isolation method (see NOTICE), but only
exports symbols actually requested by this overlay. Hardware DTS stays clean.
Requires python3-libfdt and the AOSP ufdt_apply_overlay test tool.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import libfdt


def properties(fdt, node):
    result = {}
    offset = fdt.first_property_offset(node, quiet=(libfdt.NOTFOUND,))
    while offset >= 0:
        prop = fdt.get_property_by_offset(offset)
        result[prop.name] = bytes(prop)
        offset = fdt.next_property_offset(offset, quiet=(libfdt.NOTFOUND,))
    return result


def tree(fdt):
    result = {}
    offset, depth = 0, 0
    while offset >= 0 and depth >= 0:
        result[fdt.get_path(offset)] = properties(fdt, offset)
        offset, depth = fdt.next_node(offset, depth, quiet=(libfdt.NOTFOUND,))
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mainline-dtb', type=Path, required=True)
    parser.add_argument('--stock-base', type=Path, required=True)
    parser.add_argument('--stock-overlay', type=Path, required=True)
    parser.add_argument('--ufdt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    mainline = libfdt.Fdt(args.mainline_dtb.read_bytes())
    original = tree(mainline)
    if '__symbols__' in {p.rsplit('/', 1)[-1] for p in original}:
        parser.error('Expected a plain, non-overlay mainline DTB')
    if mainline.getprop(0, 'compatible').as_stringlist()[0] != 'xiaomi,piano':
        parser.error('Expected the piano board DTB')
    overlay = libfdt.Fdt(args.stock_overlay.read_bytes())
    fixups = properties(overlay, overlay.path_offset('/__fixups__'))
    if overlay.getprop(0, 'xiaomi,miboard-id').as_uint32_list() != [9, 0]:
        parser.error('Not the expected piano stock overlay')

    def apply(source, output, log):
        proc = subprocess.run([str(args.ufdt.resolve()), str(source.resolve()),
                               str(args.stock_overlay.resolve()), str(output)],
                              capture_output=True, timeout=30)
        (out / log).write_bytes(proc.stdout + proc.stderr)
        return proc.returncode

    if apply(args.mainline_dtb, out / 'plain-merged.dtb', 'plain-overlay.log') == 0:
        parser.error('Plain overlay already works; no compatibility transformation is needed')

    mainline.resize(mainline.totalsize() + 128 * 1024)
    base = libfdt.Fdt(args.stock_base.read_bytes())
    for name in ('qcom,msm-id', 'qcom,board-id'):
        mainline.setprop(0, name, bytes(base.getprop(0, name)))
    # The disabled parent prevents stock platform devices from being populated,
    # even if a fragment replaces the target's status or compatible property.
    parent = '/firmware/piano-stock-overlay'
    mainline.add_subnode(mainline.path_offset('/firmware'), 'piano-stock-overlay')
    mainline.setprop_str(mainline.path_offset(parent), 'status', 'disabled')
    mainline.add_subnode(mainline.path_offset(parent), 'target')
    target = parent + '/target'
    phandles = [int.from_bytes(props[name], 'big')
                for props in original.values() for name in ('phandle', 'linux,phandle')
                if name in props]
    mainline.setprop_u32(mainline.path_offset(target), 'phandle', max(phandles, default=0) + 1)
    mainline.add_subnode(0, '__symbols__')
    for name in sorted(fixups):
        mainline.setprop_str(mainline.path_offset('/__symbols__'), name, target)
    mainline.pack()
    packaged = out / 'piano-boot.dtb'
    packaged.write_bytes(mainline.as_bytearray())
    merged_path = out / 'stock-overlay-simulated.dtb'
    if apply(packaged, merged_path, 'isolated-overlay.log'):
        raise RuntimeError('Isolated overlay failed; inspect isolated-overlay.log')
    merged = tree(libfdt.Fdt(merged_path.read_bytes()))
    if merged[parent].get('status') != b'disabled\0':
        raise RuntimeError('Stock overlay escaped the disabled parent')
    # Root identity is allowed to change; every existing hardware property must
    # remain byte-identical after the real libufdt merge, not just compile.
    for path, props in original.items():
        if path != '/' and merged.get(path) != props:
            raise RuntimeError(f'Stock overlay changed mainline hardware: {path}')
    identity = {'model', 'compatible', 'qcom,msm-id', 'qcom,board-id', 'xiaomi,miboard-id'}
    for name in (original['/'].keys() | merged['/'].keys()) - identity:
        if original['/'].get(name) != merged['/'].get(name):
            raise RuntimeError(f'Stock overlay changed a non-identity root property: {name}')
    unexpected = [p for p in merged if p not in original and p != '/__symbols__'
                  and p != parent and not p.startswith(parent + '/')]
    if unexpected:
        raise RuntimeError(f'Unexpected stock nodes outside isolation: {unexpected[:5]}')
    report = {
        'status': 'OFFLINE_OVERLAY_VERIFIED_RUNTIME_UNTESTED',
        'method': 'Only stock overlay fixups point below a disabled packaging-only parent',
        'fixup_count': len(fixups), 'hardware_nodes_unchanged': len(original) - 1,
        'stock_overlay_may_replace_root_identity': True,
        'inputs_sha256': {key: digest(getattr(args, key)) for key in
                          ('mainline_dtb', 'stock_base', 'stock_overlay', 'ufdt')},
        'outputs_sha256': {p.name: digest(p) for p in (packaged, merged_path)},
        'limitations': 'Runtime ABL/Gunyah overlays and memory fixups still need piano testing',
    }
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
