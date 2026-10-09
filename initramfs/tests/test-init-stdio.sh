#!/bin/sh
# SPDX-License-Identifier: MIT
# PID 1 started with fds 0-2 closed must reach its handoff.  On Wi-Fi B2 the
# kernel had no console ("unable to open an initial console"), the dracut /init
# ran piano-physical-platform, whose final echo failed, and set -e ended PID 1
# with status 1 (panic exitcode=0x00000100).  Host only, no root, no device:
# copies of the shipped init scripts run with /dev/console, the helper and the
# handoff replaced by paths in a temporary tree.
# usage: test-init-stdio.sh
# DRACUT_SH (default dash, the initrd /bin/sh) and RAM_SH (default busybox sh)
# may name other shells, e.g. the pinned ARM64 BusyBox under qemu-aarch64-static.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
repo=$here/../..
dracut_init=$repo/packaging/piano-device-support/usr/lib/dracut/modules.d/99piano/init
ram_init=$repo/initramfs/init
platform=$repo/device/platform/piano-physical-platform
dracut_sh=${DRACUT_SH:-dash}
ram_sh=${RAM_SH:-busybox sh}
fail=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

ok() { printf 'PASS %s\n' "$1"; }
skip() { printf 'SKIP %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fail=1; }

# Stand-in for the handoff (systemd or the rest of the RAM init): records the
# targets of fds 0-2 and its arguments, and writes to stdout and stderr.
cat >"$tmp/handoff" <<'STUB'
#!/bin/sh
# Read before any redirection: a shell may apply one to itself, not the child.
fds=
for fd in 0 1 2; do fds="$fds$(readlink "/proc/$$/fd/$fd")
"; done
printf '%sargs=%s\n' "$fds" "$*" >"$PIANO_TEST_REPORT"
echo handoff-stdout
echo handoff-stderr >&2
STUB
chmod 0755 "$tmp/handoff"
mkdir "$tmp/sys"  # no devicetree: the helper takes its "not piano" echo-and-exit path

# run SHELL SCRIPT CONSOLE: SCRIPT as PID 1 would see it, fds 0-2 closed;
# CONSOLE is a regular file to stand for a console, or absent. Prints the status.
run() {
	rm -f "$tmp/report" "$tmp/console"
	[ "$3" = absent ] || : >"$tmp/console"
	rc=0
	# shellcheck disable=SC2086 # $1 may be "busybox sh" or a qemu command line
	PIANO_TEST_REPORT=$tmp/report sh -c 'exec <&- >&- 2>&-; exec "$@"' sh $1 "$2" boot-arg || rc=$?
	echo "$rc"
}

# expect NAME RC CONSOLE: status 0, handoff reached with fds 0-2 on the console
# file (present) or /dev/null (absent), arguments passed, writes delivered.
expect() {
	want=/dev/null
	[ "$3" = absent ] || want=$tmp/console
	if [ "$2" != 0 ]; then
		bad "$1: exit status $2"
	elif [ ! -f "$tmp/report" ]; then
		bad "$1: handoff not reached"
	elif [ "$(cat "$tmp/report")" != "$(printf '%s\n%s\n%s\nargs=boot-arg' "$want" "$want" "$want")" ]; then
		bad "$1: fds/args $(tr '\n' ' ' <"$tmp/report")"
	elif [ "$3" = present ] && ! grep -qx handoff-stderr "$tmp/console"; then
		bad "$1: console did not receive the writes"
	else
		ok "$1"
	fi
}

# Dracut /init: exact copy apart from the device paths; refuse to run if any
# remains, so the host's systemd is never executed.
sed -e "s|/usr/libexec/piano/piano-physical-platform /sys|$platform $tmp/sys|" \
	-e "s|/usr/lib/systemd/systemd|$tmp/handoff|" \
	-e "s|/dev/console|$tmp/console|g" "$dracut_init" >"$tmp/dracut-init"
if grep -qE '/usr/lib/systemd|/usr/libexec|/dev/console' "$tmp/dracut-init" ||
	! grep -qxF "$platform $tmp/sys" "$tmp/dracut-init" ||
	! grep -qxF "exec $tmp/handoff \"\$@\"" "$tmp/dracut-init"; then
	bad 'dracut init: device paths changed; update this test'
elif ! command -v "${dracut_sh%% *}" >/dev/null 2>&1; then
	skip "dracut init: $dracut_sh unavailable"
else
	for console in absent present; do
		expect "dracut init, closed fds, console $console ($dracut_sh)" \
			"$(run "$dracut_sh" "$tmp/dracut-init" "$console")" "$console"
	done
	grep -qx 'PIANO_PHYSICAL_PLATFORM_SKIPPED: not a restored piano root' "$tmp/console" ||
		bad 'dracut init: piano-physical-platform output missing from the console'
	# Negative: without the guard this is the init of the B2 initrd; it must
	# fail exactly as there (status 1, systemd never reached).
	sed '/^if (exec </,/^fi$/d' "$tmp/dracut-init" >"$tmp/dracut-init-unguarded"
	if grep -q 'exec </dev/null' "$tmp/dracut-init-unguarded" ||
		[ $(($(wc -l <"$tmp/dracut-init") - $(wc -l <"$tmp/dracut-init-unguarded"))) != 5 ]; then
		bad 'dracut init: guard block not found; update this test'
	else
		rc=$(run "$dracut_sh" "$tmp/dracut-init-unguarded" absent)
		if [ "$rc" = 1 ] && [ ! -f "$tmp/report" ]; then
			ok "dracut init without the guard exits 1 before systemd, as on B2 ($dracut_sh)"
		else
			bad "dracut init without the guard: status $rc, handoff $([ -f "$tmp/report" ] && echo reached || echo 'not reached')"
		fi
	fi
fi

# RAM /init: its mounts, watchdog and reboot must not run on the host, so only
# the part before the first mount runs; the handoff stands for the rest.
sed -n '/^mount /q; p' "$ram_init" | sed "s|/dev/console|$tmp/console|g" >"$tmp/ram-init"
echo "exec $tmp/handoff \"\$@\"" >>"$tmp/ram-init"
if ! grep -q 'exec </dev/null >/dev/null 2>&1' "$tmp/ram-init"; then
	bad 'RAM init: no stdio guard before the first mount'
elif ! command -v "${ram_sh%% *}" >/dev/null 2>&1; then
	skip "RAM init: $ram_sh unavailable"
else
	for console in absent present; do
		expect "RAM init, closed fds, console $console ($ram_sh)" \
			"$(run "$ram_sh" "$tmp/ram-init" "$console")" "$console"
	done
	# Negative: the previous unconditional console exec ends PID 1 without a console.
	sed '/^if (exec </,/^fi$/c\
exec <'"$tmp"'/console >'"$tmp"'/console 2>&1' "$tmp/ram-init" >"$tmp/ram-init-unguarded"
	rc=$(run "$ram_sh" "$tmp/ram-init-unguarded" absent)
	if [ "$rc" != 0 ] && [ ! -f "$tmp/report" ]; then
		ok "RAM init with the unconditional console exec exits $rc without a console ($ram_sh)"
	else
		bad "RAM init with the unconditional console exec: status $rc"
	fi
fi

[ "$fail" = 0 ] && echo 'init stdio: all checks passed'
exit "$fail"
