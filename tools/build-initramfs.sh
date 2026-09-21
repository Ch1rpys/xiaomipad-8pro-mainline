#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Adapted from the erhai initramfs builder; see NOTICE.
set -euo pipefail
umask 022
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
if [[ ${1:-} == --help ]]; then
	echo 'Usage: BUSYBOX=... GEN_INIT_CPIO=... OUT_DIR=... build-initramfs.sh'
	exit 0
fi
[[ $# == 0 ]] || exit 2
busybox=$(realpath "${BUSYBOX:?set BUSYBOX to the pinned ARM64 static executable}")
gen_init_cpio=$(realpath "${GEN_INIT_CPIO:?set GEN_INIT_CPIO to the Linux host tool}")
out=${OUT_DIR:?set OUT_DIR to the diagnostic output directory}
expected=52151e7f322f926b64049cdaa1410dc3ea6485525e0624b05813791c219ae933
[[ $(sha256sum "$busybox" | cut -d' ' -f1) == "$expected" ]] || {
	echo 'BusyBox does not match the pinned Ubuntu ARM64 static executable.' >&2
	exit 1
}
[[ -x $gen_init_cpio ]]
mkdir -p "$out"
out=$(realpath "$out")
exec 9>"$out/.build.lock"
flock -n 9 || { echo 'Initramfs output is already in use.' >&2; exit 1; }
stage=$(mktemp -d "$out/stage.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
init_src="$repo/initramfs/init"
usb_src="$repo/initramfs/usb-acm"
sha256sum "$init_src" "$usb_src" "$busybox" | cut -d' ' -f1 | sha256sum | cut -d' ' -f1 >"$stage/build-id"
{
	for d in / /bin /dev /proc /sys /run /etc; do
		printf 'dir %s 0755 0 0\n' "$d"
	done
	printf 'nod /dev/console 0600 0 0 c 5 1\n'
	printf 'nod /dev/null 0666 0 0 c 1 3\n'
	printf 'file /init %s 0755 0 0\n' "$init_src"
	printf 'file /bin/usb-acm %s 0755 0 0\n' "$usb_src"
	printf 'file /bin/busybox %s 0755 0 0\n' "$busybox"
	printf 'file /etc/build-id %s 0644 0 0\n' "$stage/build-id"
	for app in sh mount mkdir cat uname sleep setsid cttyhack getty ln ls dmesg poweroff reboot; do
		printf 'slink /bin/%s busybox 0777 0 0\n' "$app"
	done
} >"$stage/cpio.list"
"$gen_init_cpio" -t 0 "$stage/cpio.list" 2>"$out/cpio.log" | gzip -n >"$out/initramfs.cpio.gz.new"
mv "$out/initramfs.cpio.gz.new" "$out/initramfs.cpio.gz"
sha256sum "$out/initramfs.cpio.gz" >"$out/initramfs.cpio.gz.sha256"
echo "Built $out/initramfs.cpio.gz (RAM diagnostic userspace, not a boot image)"
