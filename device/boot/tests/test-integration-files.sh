#!/bin/sh
# SPDX-License-Identifier: MIT
# Static checks of the boot-slot integration files in piano-device-support,
# with the host's own systemd/udev/desktop tools.  A missing tool is reported
# as SKIP, never as a pass.  usage: test-integration-files.sh [UNIT_DIR [TARGET_ROOT]]
# UNIT_DIR defaults to the host's /usr/lib/systemd/system; pass an Ubuntu
# 26.04 root's unit directory to check against the target release.
# TARGET_ROOT is an arm64 tree with that release's usr/bin/systemd-analyze and
# its libraries; the units are then also verified by it under qemu-aarch64-static.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
pkg=$here/../../../packaging/piano-device-support
units=${1:-/usr/lib/systemd/system}
target=${2:-}
fail=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

ok() { printf 'PASS %s\n' "$1"; }
skip() { printf 'SKIP %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=1; }

# systemd units: parse and resolve dependencies against a real unit set.
if command -v systemd-analyze >/dev/null 2>&1 && [ -f "$units/boot-complete.target" ]; then
	mkdir -p "$tmp/root/usr/lib/systemd/system" "$tmp/root/usr/sbin" "$tmp/root/usr/libexec/piano"
	cp -a "$units/." "$tmp/root/usr/lib/systemd/system/"
	cp "$pkg/usr/lib/systemd/system/piano-slot-success.service" \
		"$pkg/usr/lib/systemd/system/piano-thp.service" "$tmp/root/usr/lib/systemd/system/"
	install -m 0755 "$here/../piano-slot-success" "$tmp/root/usr/sbin/piano-slot-success"
	printf '#!/bin/sh\n' >"$tmp/root/usr/libexec/piano/piano-thp-live"
	chmod 0755 "$tmp/root/usr/libexec/piano/piano-thp-live"
	verify() {
		for u in piano-slot-success.service piano-thp.service; do
			# shellcheck disable=SC2086 # $1 may be a qemu command line
			if out=$($1 verify --man=no --root="$tmp/root" "$u" 2>&1 | grep -i 'piano'); then
				bad "systemd-analyze verify $u: $out"
			else
				ok "systemd-analyze verify $u ($($1 --version | head -n1))"
			fi
		done
	}
	verify systemd-analyze
	if [ -n "$target" ] && [ -x "$target/usr/bin/systemd-analyze" ] && command -v qemu-aarch64-static >/dev/null 2>&1; then
		verify "qemu-aarch64-static -L $target $target/usr/bin/systemd-analyze"
	elif [ -n "$target" ]; then
		skip 'target systemd-analyze'
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

# piano-thp.service is started by udev for the touch node only: as a boot-target
# want it would hold multi-user.target and GDM for the device timeout.
thp=$pkg/usr/lib/systemd/system/piano-thp.service
if grep -q '^\[Install\]' "$thp"; then
	bad 'piano-thp.service has an [Install] section'
fi
grep -qF 'ENV{SYSTEMD_WANTS}+="piano-thp.service"' "$pkg/usr/lib/udev/rules.d/71-piano.rules" ||
	bad '71-piano.rules does not start piano-thp.service for the touch node'
grep -qF 'deb-systemd-helper purge piano-thp.service' "$here/../../../tools/build-device-debs.py" ||
	bad 'postinst does not purge the multi-user.target link of older versions'
if grep -q 'enable piano-thp.service' "$here/../../../tools/build-device-debs.py"; then
	bad 'postinst still enables piano-thp.service'
fi

# Kernel hooks: only unique <version>-piano<ABI> releases, newest first, own the
# boot image set; removal cleans up.
for h in etc/kernel/postinst.d/zz-piano-boot etc/initramfs/post-update.d/zz-piano-boot \
	etc/kernel/postrm.d/zz-piano-boot; do
	sh -n "$pkg/$h" || bad "$h: shell syntax"
done
for h in etc/kernel/postinst.d/zz-piano-boot etc/initramfs/post-update.d/zz-piano-boot; do
	# shellcheck disable=SC2016 # literal hook text
	grep -qF 'case "${1:-}" in *-piano[0-9]*) ;; *) exit 0;; esac' "$pkg/$h" ||
		bad "$h accepts releases other than -piano<ABI>"
	grep -qF 'linux-version sort | tail -n 1' "$pkg/$h" || bad "$h does not keep to the newest piano kernel"
done
# shellcheck disable=SC2016 # literal hook text
grep -qF 'exec /usr/sbin/piano-boot-update --removed "$1"' "$pkg/etc/kernel/postrm.d/zz-piano-boot" ||
	bad 'postrm.d hook does not clean up after a removed piano kernel'

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
