#!/bin/bash
# SPDX-License-Identifier: MIT
# Called by build-rootfs-image.py in a private mount namespace. Trusted inputs only.
set -euo pipefail
# Other hosts run the aarch64 target through binfmt_misc (qemu-user with the F flag);
# build-rootfs-image.py checks that handler before choosing this backend.
[[ $# == 3 && $EUID == 0 ]] || exit 2
image=$(realpath -e -- "$1")
inputs=$(realpath -e -- "$2")
out=$(realpath -e -- "$3")
[[ -f $image && ! -L $image && -f $inputs ]] || exit 2
mp="$out/mount"
mkdir -m 700 "$mp"
mkdir -p "$out/guest"
mounted=()
finish() {
    status=$?
    trap - EXIT
    set +e
    for ((i=${#mounted[@]}-1; i>=0; i--)); do
        umount -- "${mounted[i]}" || status=1
    done
    rmdir "$mp" || status=1
    exit "$status"
}
trap finish EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
mount -t ext4 -o loop,rw -- "$image" "$mp"
mounted+=("$mp")
for d in proc sys dev dev/pts run tmp; do
    [[ -d $mp/$d && $(realpath -e -- "$mp/$d") == "$mp/$d" ]] || exit 1
done
for d in proc sys dev dev/pts; do
    mount --bind "/$d" "$mp/$d"
    mounted+=("$mp/$d")
    mount --make-private "$mp/$d"
done
mount -o remount,bind,ro -- "$mp/sys"
mount -t tmpfs -o mode=755 tmpfs "$mp/run"
mounted+=("$mp/run")
mount -t tmpfs -o mode=1777 tmpfs "$mp/tmp"
mounted+=("$mp/tmp")
mkdir -m 700 "$mp/run/piano-inputs"
tar -xf "$inputs" -C "$mp/run/piano-inputs"
mkdir "$mp/run/piano-out"
mount --bind "$out/guest" "$mp/run/piano-out"
mounted+=("$mp/run/piano-out")
env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C.UTF-8 LANGUAGE=C ${QEMU_CPU:+QEMU_CPU=$QEMU_CPU} \
    SYSTEMD_OFFLINE=1 DEBIAN_FRONTEND=noninteractive \
    chroot "$mp" /bin/bash /run/piano-inputs/chroot.sh
# Discard the free blocks from the host, after the steps (trim_target in chroot.sh): the
# loop device punches them out of the image file.  Through binfmt_misc, an fstrim in the
# chroot would fail: qemu-user does not pass the FITRIM ioctl through.
fstrim -v "$mp"
