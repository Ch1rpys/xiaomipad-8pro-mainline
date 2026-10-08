#!/bin/sh
# SPDX-License-Identifier: MIT
# Static checks of the developer-mode files in piano-device-support with the
# host's own systemd, OpenSSH and shells.  A missing tool is reported as SKIP,
# never as a pass.  usage: test-devmode-files.sh [UNIT_DIR [TARGET_ROOT]]
# UNIT_DIR defaults to the host's /usr/lib/systemd/system; pass an Ubuntu
# 26.04 root's unit directory to check against the target release.
# TARGET_ROOT is an arm64 tree such as that root plus an extracted
# openssh-server package: its sshd@.service, ssh.socket and ssh.service join
# the unit set, and its usr/bin/systemd-analyze and usr/sbin/sshd, with their
# libraries, also check the files through qemu-aarch64-static.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$here/../../..
pkg=$repo/packaging/piano-device-support
units=${1:-/usr/lib/systemd/system}
target=${2:-}
# Target binaries run under user-mode QEMU; empty when not available.
qemu_target() {
	[ -n "$target" ] && [ -x "$target/$1" ] && command -v qemu-aarch64-static >/dev/null 2>&1 &&
		echo "qemu-aarch64-static -L $target $target/$1"
}
fail=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

ok() { printf 'PASS %s\n' "$1"; }
skip() { printf 'SKIP %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=1; }
has() { grep -qxF "$2" "$1" || bad "${1#"$pkg"/} lacks: $2"; }

net() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$repo/initramfs/network.json" "$1"; }
dev_ip=$(net device_ip)
dev_mac=$(net device_mac)
host_ip=$(net host_ip)

sysunits=$pkg/usr/lib/systemd/system
service=$sysunits/piano-devmode.service
socket=$sysunits/piano-devmode-ssh.socket
session=$sysunits/piano-devmode-ssh@.service
network=$pkg/usr/lib/systemd/network/50-piano-devmode.network
sshd_config=$pkg/usr/lib/piano/devmode/sshd_config
scripts="$pkg/usr/libexec/piano/devmode-gadget $pkg/usr/sbin/piano-devmode $pkg/usr/sbin/piano-reboot-bootloader"

# systemd units: parse and resolve dependencies against a real unit set.
r=$tmp/root
mkdir -p "$r/usr/lib/systemd/system" "$r/usr/sbin" "$r/usr/libexec/piano"
cp -a "$units/." "$r/usr/lib/systemd/system/"
if [ -n "$target" ]; then
	for u in sshd@.service ssh.socket ssh.service; do
		cp "$target/usr/lib/systemd/system/$u" "$r/usr/lib/systemd/system/"
	done
fi
cp "$service" "$socket" "$session" "$r/usr/lib/systemd/system/"
for s in $scripts; do
	install -m 0755 "$s" "$r${s#"$pkg"}"
done
printf '#!/bin/sh\n' >"$r/usr/sbin/sshd"
chmod 0755 "$r/usr/sbin/sshd"
verify() {
	for u in piano-devmode.service piano-devmode-ssh.socket piano-devmode-ssh@test.service; do
		# shellcheck disable=SC2086
		if out=$($1 verify --man=no --root="$r" "$u" 2>&1 | grep -i 'piano'); then
			bad "systemd-analyze verify $u: $out"
		else
			ok "systemd-analyze verify $u ($($1 --version | head -n1))"
		fi
	done
}
if ! [ -f "$units/usb-gadget.target" ]; then
	skip "usb-gadget.target not in $units"
else
	if command -v systemd-analyze >/dev/null 2>&1; then verify systemd-analyze; else skip 'systemd-analyze'; fi
	if sa=$(qemu_target usr/bin/systemd-analyze); then verify "$sa"; else skip 'target systemd-analyze'; fi
fi

# Unit decisions: off by default, never in debug boots, socket bound to devmode.
has "$service" 'ConditionKernelCommandLine=!piano.debug=1'
has "$service" 'WantedBy=usb-gadget.target'
has "$service" 'Wants=systemd-networkd.service piano-devmode-ssh.socket'
has "$service" 'ExecStartPre=/usr/sbin/piano-devmode check'
has "$service" 'ExecStart=/usr/libexec/piano/devmode-gadget start'
has "$service" 'ExecStop=/usr/libexec/piano/devmode-gadget stop'
has "$socket" "ListenStream=$dev_ip:22"
has "$socket" 'Accept=yes'
has "$socket" 'FreeBind=yes'
has "$socket" 'BindsTo=piano-devmode.service'
has "$session" 'PartOf=piano-devmode.service'
has "$session" "ExecStart=-/usr/sbin/sshd -i -f /usr/lib/piano/devmode/sshd_config"
if grep -q '^\[Install\]' "$socket" "$session"; then
	bad 'the socket or session template has its own [Install] section'
fi
postinst=$(grep -n 'deb-systemd-helper enable' "$repo/tools/build-device-debs.py" || true)
case "$postinst" in
'') bad 'build-device-debs.py postinst enable line not found' ;;
*piano-devmode*) bad 'the package postinst enables developer mode' ;;
*) ok 'developer mode is not enabled by the package' ;;
esac
grep -q "openssh-server" "$repo/tools/build-device-debs.py" ||
	bad 'build-device-debs.py does not recommend openssh-server'

# Network: the contract of initramfs/network.json, no route or DNS for the host.
has "$network" "MACAddress=$dev_mac"
has "$network" 'KernelCommandLine=!piano.debug=1'
has "$network" "Address=$dev_ip/24"
has "$network" 'DHCPServer=yes'
has "$network" 'KeepConfiguration=yes'
pool=$(sed -n 's/^PoolOffset=//p' "$network")
[ "${dev_ip%.*}.$pool" = "$host_ip" ] || bad "DHCP pool offset $pool does not give $host_ip"
has "$network" 'PoolSize=1'
for k in EmitRouter EmitDNS EmitNTP EmitSIP EmitTimezone; do
	has "$network" "$k=no"
done
grep -q "ATTR{address}==\"$dev_mac\", ENV{NM_UNMANAGED}=\"1\"" "$pkg/usr/lib/udev/rules.d/71-piano.rules" ||
	bad 'NetworkManager is not kept off the developer-mode link'

# OpenSSH configuration: syntax and effective values with a throw-away host key.
sshd_check() {
	# shellcheck disable=SC2086
	if out=$($1 -t -f "$sshd_config" -h "$tmp/hostkey" 2>&1); then
		ok "sshd -t ($($1 -V 2>&1 | head -n1))"
	else
		bad "sshd -t: $out"
	fi
	# shellcheck disable=SC2086
	eff=$($1 -T -f "$sshd_config" -h "$tmp/hostkey" -C user=nobody,host=h,addr=$host_ip 2>/dev/null || true)
	for line in 'permitrootlogin no' 'passwordauthentication yes' 'kbdinteractiveauthentication no' 'usepam yes' \
		'subsystem sftp internal-sftp'; do
		printf '%s\n' "$eff" | sed 's/ *$//' | grep -qxF "$line" || bad "sshd -T lacks: $line"
	done
}
if command -v ssh-keygen >/dev/null 2>&1; then
	ssh-keygen -q -t ed25519 -N '' -f "$tmp/hostkey"
	if [ -x /usr/sbin/sshd ]; then sshd_check /usr/sbin/sshd; else skip 'host sshd'; fi
	if sshd=$(qemu_target usr/sbin/sshd); then sshd_check "$sshd"; else skip 'target sshd'; fi
else
	skip 'ssh-keygen unavailable'
fi

# Shell scripts: POSIX parsers, then shellcheck when installed.
for s in $scripts; do
	for shell in sh dash bash; do
		if command -v "$shell" >/dev/null 2>&1; then
			"$shell" -n "$s" || bad "$shell -n ${s#"$pkg"/}"
		fi
	done
done
ok 'sh/dash/bash -n'
if command -v shellcheck >/dev/null 2>&1; then
	# shellcheck disable=SC2086
	if shellcheck -s sh $scripts; then ok 'shellcheck'; else bad 'shellcheck'; fi
else
	skip 'shellcheck not installed'
fi

# polkit action: well-formed, admin authentication without keep.
policy=$pkg/usr/share/polkit-1/actions/io.github.piano.devmode.policy
if python3 - "$policy" <<'EOF'
import sys, xml.etree.ElementTree as ET
a = ET.parse(sys.argv[1]).getroot().findall('action')
assert len(a) == 1 and a[0].get('id') == 'io.github.piano.devmode'
d = a[0].find('defaults')
assert [d.find(k).text for k in ('allow_any', 'allow_inactive', 'allow_active')] == ['auth_admin'] * 3
n = {x.get('key'): x.text for x in a[0].findall('annotate')}
assert n == {'org.freedesktop.policykit.exec.path': '/usr/sbin/piano-devmode'}, n
EOF
then ok 'polkit action'; else bad 'polkit action'; fi

[ "$fail" = 0 ] && echo 'developer mode files: all checks passed'
exit "$fail"
