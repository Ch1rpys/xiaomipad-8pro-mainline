#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Structural check of a compiled AudioReach topology, as the Linux q6apm driver will use it.

Decodes the binary with `alsatplg -d` and reads each module's AudioReach tuples (token numbers
of include/uapi/sound/snd_ar_tokens.h): instance ID (201), module ID (200), maximum input and
output ports (202, 203), source output port (206), destination input port (207) and destination
instance (208/209). Checks:

- link-dropped: a module names a destination instance, but its source output port or the
  destination input port is 0. sound/soc/qcom/qdsp6/topology.c keeps a link only when all
  three are non-zero, so the DSP receives the two modules unconnected (GRAPH_OPEN fails);
- dangling: the destination instance is not defined in the topology;
- duplicate: two modules share an instance ID;
- ports: a kept link uses an even output port or an odd input port (AudioReach numbers outputs
  1, 3, ... and inputs 2, 4, ...), or a module links more outputs than max_op_ports allows.

Links between subgraphs (stream to device through a mixer route) are made by the kernel from
the route, not from these tuples, and are not checked here. Exit status 0 when no error, 1 when
an error is found, 2 for unusable input.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

TOK = {'iid': 201, 'mid': 200, 'max_ip': 202, 'max_op': 203, 'src_port': 206, 'dst_port': 207,
       'src_iid': 208, 'dst_iid': 209}


def decode(path):
    if path.suffix == '.conf':
        return path.read_text()
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / 'decoded.conf'
        p = subprocess.run(['alsatplg', '-d', str(path), '-o', str(out)], capture_output=True, text=True)
        if p.returncode or not out.exists():
            raise SystemExit(f'alsatplg -d failed: {p.stderr.strip()}')
        return out.read_text()


def modules(text):
    mods = {}
    for m in re.finditer(r"'([^']+):tuple0' \{\s*tokens '[^']*'\s*tuples \{(.*?)\n\t\}", text, re.S):
        vals = {int(k): int(v) for k, v in re.findall(r'token(\d+) (-?\d+)', m.group(2))}
        if TOK['mid'] in vals and TOK['iid'] in vals:
            mods[m.group(1)] = {k: vals.get(t, 0) for k, t in TOK.items()}
    return mods


def check(mods):
    errors, links = [], []
    by_iid = {}
    for name, v in mods.items():
        if v['iid'] in by_iid:
            errors.append({'kind': 'duplicate', 'iid': v['iid'], 'modules': [by_iid[v['iid']], name]})
        by_iid[v['iid']] = name
    for name, v in sorted(mods.items()):
        if not v['dst_iid']:
            continue
        if v['dst_iid'] not in by_iid:
            errors.append({'kind': 'dangling', 'module': name, 'dst_iid': v['dst_iid']})
            continue
        if not v['src_port'] or not v['dst_port']:
            errors.append({'kind': 'link-dropped', 'module': name, 'module_id': f"0x{v['mid']:08x}",
                           'src_port': v['src_port'], 'dst': by_iid[v['dst_iid']], 'dst_port': v['dst_port']})
            continue
        if v['src_port'] % 2 == 0 or v['dst_port'] % 2 == 1 or v['max_op'] < 1:
            errors.append({'kind': 'ports', 'module': name, 'src_port': v['src_port'],
                           'dst_port': v['dst_port'], 'max_op': v['max_op']})
        links.append([name, v['src_port'], by_iid[v['dst_iid']], v['dst_port']])
    return {'modules': len(mods), 'links': links, 'errors': errors,
            'verdict': 'FAIL' if errors else 'PASS'}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('topology', type=Path, help='compiled -tplg.bin, or an alsatplg -d .conf')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    try:
        mods = modules(decode(a.topology))
    except OSError as e:
        print(e, file=sys.stderr)
        return 2
    if not mods:
        print('no AudioReach module tuples found', file=sys.stderr)
        return 2
    r = check(mods)
    out = json.dumps(r, indent=1)
    if a.json:
        a.json.write_text(out + '\n')
    print(out)
    return 0 if r['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
