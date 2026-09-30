#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Adapted from the erhai initramfs builder; see NOTICE.
set -euo pipefail
umask 022
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
if [[ ${1:-} == --help ]]; then
	echo 'Usage: BUSYBOX=... GEN_INIT_CPIO=... OUT_DIR=... [FIRMWARE_DIR=...] [MODULES_DIR=...] build-initramfs.sh'
	echo 'MODULES_DIR: optional verified stage-kernel-modules output; no automatic module loading.'
	echo 'FIRMWARE_DIR: optional private tree copied to /lib/firmware/<relative path>;'
	echo 'its manifest (path size sha256) goes to /etc/piano-firmware and OUT_DIR/firmware-manifest.'
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
usb_src="$repo/initramfs/usb-diag"
network_src="$repo/initramfs/network.json"
ubuntu_src="$repo/initramfs/prepare-ubuntu"
state_src="$repo/initramfs/ubuntu-state"
# Optional private firmware for drivers that request it at probe or first open.
# Only regular files with plain relative paths; the bytes never leave OUT_DIR.
rm -f "$out/firmware-manifest"
if [[ -n ${FIRMWARE_DIR:-} ]]; then
	fw_dir=$(realpath "$FIRMWARE_DIR")
	[[ -d $fw_dir ]] || { echo "FIRMWARE_DIR is not a directory: $fw_dir" >&2; exit 1; }
	[[ -z $(find "$fw_dir" -mindepth 1 ! -type f ! -type d -print -quit) ]] || {
		echo 'FIRMWARE_DIR may only contain regular files and directories.' >&2; exit 1;
	}
	(cd "$fw_dir" && find . -type f -printf '%P\n' | LC_ALL=C sort) >"$stage/firmware-files"
	[[ -s $stage/firmware-files ]] || { echo 'FIRMWARE_DIR contains no files.' >&2; exit 1; }
	while IFS= read -r rel; do
		[[ $rel =~ ^[A-Za-z0-9._+-]+(/[A-Za-z0-9._+-]+)*$ && ! $rel =~ (^|/)\.\.?(/|$) ]] || {
			echo "Unsupported firmware path: $rel" >&2; exit 1;
		}
		printf '%s %s %s\n' "$rel" "$(stat -c %s -- "$fw_dir/$rel")" \
			"$(sha256sum -- "$fw_dir/$rel" | cut -d' ' -f1)"
	done <"$stage/firmware-files" >"$stage/piano-firmware"
fi
rm -f "$out/module-manifest.json"
if [[ -n ${MODULES_DIR:-} ]]; then
	python3 "$repo/tools/prepare-module-initramfs.py" --modules-tree "$MODULES_DIR" \
		--stage "$stage/modules" >"$stage/modules.list"
fi
{
	sha256sum "$init_src" "$usb_src" "$network_src" "$ubuntu_src" "$state_src" "$busybox" | cut -d' ' -f1
	[[ ! -f $stage/piano-firmware ]] || sha256sum "$stage/piano-firmware" | cut -d' ' -f1
	if [[ -f $stage/modules.list ]]; then
		sha256sum "$stage/modules/etc/piano-modules.sha256" "$stage/modules/bin/piano-modules" | cut -d' ' -f1
	fi
} | sha256sum | cut -d' ' -f1 >"$stage/build-id"
python3 - "$network_src" "$stage/piano-network" <<'PY'
import json, pathlib, shlex, sys
network = json.loads(pathlib.Path(sys.argv[1]).read_text())
pathlib.Path(sys.argv[2]).write_text(''.join(
    f'PIANO_{key.upper()}={shlex.quote(value)}\n' for key, value in network.items()))
PY
{
	for d in . /bin /dev /proc /sys /run /etc; do
		printf 'dir %s 0755 0 0\n' "$d"
	done
	printf 'nod /dev/console 0600 0 0 c 5 1\n'
	printf 'nod /dev/null 0666 0 0 c 1 3\n'
	printf 'file /init %s 0755 0 0\n' "$init_src"
	printf 'file /bin/usb-diag %s 0755 0 0\n' "$usb_src"
	printf 'file /bin/prepare-ubuntu %s 0755 0 0\n' "$ubuntu_src"
	printf 'file /bin/ubuntu-state %s 0755 0 0\n' "$state_src"
	printf 'file /etc/piano-network %s 0644 0 0\n' "$stage/piano-network"
	printf 'file /bin/busybox %s 0755 0 0\n' "$busybox"
	printf 'file /etc/build-id %s 0644 0 0\n' "$stage/build-id"
	if [[ -f $stage/piano-firmware || -f $stage/modules.list ]]; then
		printf 'dir /lib 0755 0 0\n'
	fi
	[[ ! -f $stage/modules.list ]] || cat "$stage/modules.list"
	if [[ -f $stage/piano-firmware ]]; then
		printf 'file /etc/piano-firmware %s 0644 0 0\n' "$stage/piano-firmware"
		printf 'dir /lib/firmware 0755 0 0\n'
		sed -n 's|/[^/]*$||p' "$stage/firmware-files" | LC_ALL=C sort -u | while IFS= read -r d; do
			path=
			IFS=/ read -ra parts <<<"$d"
			for part in "${parts[@]}"; do
				path+=/$part
				printf 'dir /lib/firmware%s 0755 0 0\n' "$path"
			done
		done | awk '!seen[$0]++'
		while IFS= read -r rel; do
			printf 'file /lib/firmware/%s %s 0644 0 0\n' "$rel" "$fw_dir/$rel"
		done <"$stage/firmware-files"
	fi
	for app in sh mount mkdir cat uname sleep setsid cttyhack getty ln ls dmesg poweroff reboot ip touch udhcpd telnetd; do
		printf 'slink /bin/%s busybox 0777 0 0\n' "$app"
	done
} >"$stage/cpio.list"
"$gen_init_cpio" -t 0 "$stage/cpio.list" 2>"$out/cpio.log" | gzip -n >"$out/initramfs.cpio.gz.new"
mv "$out/initramfs.cpio.gz.new" "$out/initramfs.cpio.gz"
[[ ! -f $stage/piano-firmware ]] || cp "$stage/piano-firmware" "$out/firmware-manifest"
[[ ! -f $stage/modules.list ]] || cp "$stage/modules/etc/piano-modules.json" "$out/module-manifest.json"
sha256sum "$out/initramfs.cpio.gz" >"$out/initramfs.cpio.gz.sha256"
echo "Built $out/initramfs.cpio.gz (RAM diagnostic userspace, not a boot image)"
