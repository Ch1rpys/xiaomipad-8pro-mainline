#!/bin/sh
# SPDX-License-Identifier: MIT
# Static checks of the boot-slot integration files in piano-device-support,
# with the host's own systemd/udev/desktop tools.  A missing tool is reported
# as SKIP, never as a pass.  usage: test-integration-files.sh [UNIT_DIR]
# UNIT_DIR defaults to the host's /usr/lib/systemd/system; pass an Ubuntu
# 26.04 root's unit directory to check against the target release.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
pkg=$here/../../../packaging/piano-device-support
units=${1:-/usr/lib/systemd/system}
fail=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

ok() { printf 'PASS %s\n' "$1"; }
skip() { printf 'SKIP %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=1; }

# systemd unit: parse and resolve dependencies against a real unit set.
if command -v systemd-analyze >/dev/null 2>&1 && [ -f "$units/boot-complete.target" ]; then
	mkdir -p "$tmp/root/usr/lib/systemd/system" "$tmp/root/usr/sbin"
	cp -a "$units/." "$tmp/root/usr/lib/systemd/system/"
	cp "$pkg/usr/lib/systemd/system/piano-slot-success.service" "$tmp/root/usr/lib/systemd/system/"
	install -m 0755 "$here/../piano-slot-success" "$tmp/root/usr/sbin/piano-slot-success"
	if out=$(systemd-analyze verify --man=no --root="$tmp/root" piano-slot-success.service 2>&1 | grep -i 'piano-slot-success'); then
		bad "systemd-analyze verify piano-slot-success.service: $out"
	else
		ok 'systemd-analyze verify piano-slot-success.service'
	fi
else
	skip 'systemd-analyze or boot-complete.target unavailable'
fi
unit=$pkg/usr/lib/systemd/system/piano-slot-success.service
for line in 'Requires=boot-complete.target' 'ConditionKernelCommandLine=piano.boot=persistent' \
	'ExecStart=/usr/sbin/piano-slot-success --mark' 'WantedBy=multi-user.target' 'Type=oneshot'; do
	grep -qxF "$line" "$unit" || bad "unit lacks $line"
done
grep -q 'piano-slot-success.service' "$here/../../../tools/build-device-debs.py" ||
	bad 'build-device-debs.py does not enable piano-slot-success.service'

# udev rule: parse with udevadm; the decisions are the controller and type GUID.
rule=$pkg/usr/lib/udev/rules.d/90-piano-internal-storage.rules
if command -v udevadm >/dev/null 2>&1 && udevadm verify --help >/dev/null 2>&1; then
	if udevadm verify --resolve-names=never "$rule" >/dev/null; then
		ok 'udevadm verify 90-piano-internal-storage.rules'
	else
		bad 'udevadm verify 90-piano-internal-storage.rules'
	fi
else
	skip 'udevadm verify unavailable'
fi
# Observed on piano: kmsg "ufshcd-qcom 1d84000.ufs", sysfs .../platform/soc@0/1d84000.ufs/host0/...
grep -qx 'SUBSYSTEMS=="platform", DRIVERS=="ufshcd-qcom", ENV{UDISKS_IGNORE}="1"' "$rule" ||
	bad 'rule does not restrict UDISKS_IGNORE to the ufshcd-qcom platform device'
if grep -v '^#' "$rule" | grep -q 'ufshc"'; then
	bad 'rule matches the ABL bootdevice name, which does not exist in Linux sysfs'
fi
grep -qx 'ENV{ID_PART_ENTRY_TYPE}=="0fc63daf-8483-4772-8e79-3d69d8477de4", GOTO="piano_internal_storage_end"' "$rule" ||
	bad 'rule does not exempt the Linux filesystem type GUID'
grep -qx 'ENV{DEVTYPE}!="partition", GOTO="piano_internal_storage_end"' "$rule" ||
	bad 'rule does not leave whole-disk nodes alone'
if grep -Eq 'PARTLABEL|ID_PART_ENTRY_NAME|ID_PART_ENTRY_UUID|sd[a-f][0-9]' "$rule"; then
	bad 'rule depends on labels, partition GUIDs or sdX names'
fi

[ "$fail" = 0 ] && echo 'integration files: all checks passed'
exit "$fail"
