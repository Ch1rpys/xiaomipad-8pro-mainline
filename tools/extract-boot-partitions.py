#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write this unit's boot-partitions.json from `sfdisk --json` of its boot LUN.

piano-boot-switch writes slot A only into the partitions this map pins, and
compares every field with the live GPT and the LUN before it writes.  The
input is the `sfdisk --json` output of the UFS LUN whose GPT holds boot_a and
boot_b (LUN 4 on piano), for example read in the maintenance RAM image.  Each
slot-A partition must appear once and be exactly the capacity that this
unit's boot-profile.json gives its image, the size every boot set is built to.
The output carries this unit's GUIDs: do not commit or share it.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'device/boot'))
import piano_bootslot as slot  # noqa: E402

BOOT_LUN = 4  # the only LUN piano-boot-switch accepts in the map


def guid(value, what):
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ValueError(f'{what} is not a GUID: {value!r}') from None


def boot_partitions(document, profile):
    """Map rows (label, partuuid, disk_guid, lun, start_bytes, bytes) for slot A."""
    table = document.get('partitiontable') if isinstance(document, dict) else None
    if not isinstance(table, dict) or table.get('label') != 'gpt':
        raise ValueError('Not the sfdisk --json output of a GPT disk')
    lbs = table.get('sectorsize')
    if lbs not in (512, 4096):
        raise ValueError(f'sectorsize {lbs!r}: need sfdisk 2.38 or later and 512- or 4096-byte sectors')
    entries = table.get('partitions') or []
    if not any(e.get('name') == 'boot_b' for e in entries):
        raise ValueError('This disk has no boot_b entry: it is not the boot LUN, whose GPT holds boot_a and boot_b')
    disk_guid = guid(table.get('id'), 'Disk id')
    rows = []
    for name in slot.NAMES:
        label = name + '_a'
        hits = [e for e in entries if e.get('name') == label]
        if len(hits) != 1:
            raise ValueError(f'Need exactly one {label} entry, found {len(hits)}')
        start, size = hits[0].get('start'), hits[0].get('size')
        if type(start) is not int or type(size) is not int or start <= 0 or size <= 0:
            raise ValueError(f'{label}: invalid start or size')
        capacity = profile[name]['capacity']
        if size * lbs != capacity:
            raise ValueError(f'{label} is {size * lbs} B, but boot-profile.json gives {name} {capacity} B')
        rows.append({'label': label, 'partuuid': guid(hits[0].get('uuid'), f'{label} uuid'),
                     'disk_guid': disk_guid, 'lun': BOOT_LUN, 'start_bytes': start * lbs, 'bytes': size * lbs})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--input', required=True, help='sfdisk --json output of the boot LUN; - reads standard input')
    ap.add_argument('--profile', type=Path, required=True, help="this unit's boot-profile.json")
    ap.add_argument('--output', type=Path, required=True, help='new file (mode 0600); an existing file is kept')
    a = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if a.input == '-' else Path(a.input).read_text()
        rows = boot_partitions(json.loads(text), json.loads(a.profile.read_text()))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f'extract-boot-partitions: {error}; nothing was written') from None
    descriptor = os.open(a.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(rows, stream, indent=2)
        stream.write('\n')
    for row in rows:
        print(f'{row["label"]}: LUN {row["lun"]}, start {row["start_bytes"]} B, {row["bytes"]} B')
    print(f'Wrote {a.output}; it holds this unit\'s GUIDs: do not commit or share it.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
