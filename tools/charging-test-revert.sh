#!/bin/sh
# SPDX-License-Identifier: MIT
# One-boot test cleanup; use the project's existing serial/layout/set checks.
set -eu
serial=$1
previous=$2
python3 - "$serial" <<'PY'
import sys
sys.path.insert(0, '/usr/lib/piano/boot')
from piano_bootslot import Host, require_piano, firmware_serial
host = Host()
host.require_root()
require_piano(host)
if firmware_serial(host) != sys.argv[1]:
    raise SystemExit('Firmware serial mismatch; refusing rollback')
PY
/usr/sbin/piano-boot-switch import-ubuntu --from "$previous"
/usr/sbin/piano-boot-switch to-ubuntu --reboot
