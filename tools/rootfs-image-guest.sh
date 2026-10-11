#!/bin/sh
# SPDX-License-Identifier: MIT
# Guest half of build-rootfs-image.py: runs as root in a disposable QEMU ARM64
# guest whose own root is the read-only pristine Desktop SquashFS.  It applies
# docs/AGENT-GUIDE.md section 4.4 to the target ext4 on a second disk: image
# policy, /etc/piano/layout.json and fstab, then dpkg --install in a chroot
# with policy-rc.d and SYSTEMD_OFFLINE=1, so the distribution kernel hooks run
# dracut and the piano hooks inside the target, and purges the base's generic
# kernels and kdump.  It then builds the release boot image set into the
# store and removes per-machine state and the base's package indexes.  The target
# never boots.  Inputs are a tar on the third disk, results a tar on the fourth.
set -eu
IN=/run/piano-inputs
OUT=/run/piano-out
T=/run/piano-target
. "$IN/params.sh"
mkdir -p "$OUT" "$T"
exec >"$OUT/install.log" 2>&1
# The console copy is for following progress; the log travels in the result tar.
tail -n +1 -f "$OUT/install.log" >/dev/console &

mounted=''
finish() {
	status=$?
	set +e
	for m in $mounted; do umount "$m"; done
	echo "PIANO_ROOTFS_EXIT status=$status"
	sync
	# The host reads this tar whether or not the steps passed.
	tar -cf "$result" -C "$OUT" .
	sync
	exit "$status"
}
step() { echo "PIANO_ROOTFS_STEP $*"; }
fail() { echo "PIANO_ROOTFS_FAIL $*"; exit 1; }

# Fail closed on the disk order before anything is written.
for pair in vda:piano-helper vdb:piano-target vdc:piano-inputs vdd:piano-result; do
	dev=${pair%%:*}
	[ "$(cat "/sys/block/$dev/serial")" = "${pair#*:}" ] || fail "/dev/$dev is not ${pair#*:}"
done
result=/dev/vdd
trap finish EXIT

step mount target
mount -t ext4 /dev/vdb "$T"
mounted="$T"
[ -z "$(ls -A "$T/home")" ] || fail 'the base has entries in /home'
[ ! -e "$T/etc/fstab" ] || fail 'the base already has /etc/fstab'
[ ! -e "$T/etc/piano" ] || fail 'the base already has /etc/piano'

step image policy
# The same policy as build-ubuntu-ext4.py: official Ports sources, no CD-ROM
# source, cloud-init disabled.
install -m 644 "$IN/files/etc/apt/sources.list.d/ubuntu.sources" "$T/etc/apt/sources.list.d/ubuntu.sources"
[ -f "$T/etc/apt/sources.list.d/cdrom.sources" ] || fail 'no CD-ROM source to remove'
rm "$T/etc/apt/sources.list.d/cdrom.sources"
: >"$T/etc/cloud/cloud-init.disabled"
chmod 644 "$T/etc/cloud/cloud-init.disabled"
# A device name instead of the base's localhost.localdomain.  GNOME Initial
# Setup replaces the static hostname with its "Computer" field (the user name
# unless edited); the pretty hostname stays, and BlueZ prefers it.
install -m 644 "$IN/files/etc/hostname" "$T/etc/hostname"
[ ! -e "$T/etc/machine-info" ] || fail 'the base already has /etc/machine-info'
install -m 644 "$IN/files/etc/machine-info" "$T/etc/machine-info"

step piano layout
# layout.json must exist before the kernel package is configured: it enables
# the dracut module 99piano and the zz-piano-boot hooks.
install -d -m 755 "$T/etc/piano"
install -m 600 "$IN/files/etc/piano/layout.json" "$T/etc/piano/layout.json"
install -m 644 "$IN/files/etc/fstab" "$T/etc/fstab"

step chroot mounts
mount -t proc proc "$T/proc"; mounted="$T/proc $mounted"
mount -t sysfs -o ro sysfs "$T/sys"; mounted="$T/sys $mounted"
mount --bind /dev "$T/dev"; mounted="$T/dev $mounted"
mount --bind /dev/pts "$T/dev/pts"; mounted="$T/dev/pts $mounted"
# Nothing written below /run or /tmp of the target reaches the image.
mount -t tmpfs -o mode=755 tmpfs "$T/run"; mounted="$T/run $mounted"
mount -t tmpfs -o mode=1777 tmpfs "$T/tmp"; mounted="$T/tmp $mounted"

step install packages
[ ! -e "$T/usr/sbin/policy-rc.d" ] || fail 'the base already has policy-rc.d'
printf '#!/bin/sh\nexit 101\n' >"$T/usr/sbin/policy-rc.d"
chmod 755 "$T/usr/sbin/policy-rc.d"
# The kernel postinst runs dracut once; the dracut upgrade's update-initramfs
# trigger would generate the same initrd again.  Standard initramfs-tools
# setting, present only while the packages are installed.
[ ! -e "$T/etc/initramfs-tools/update-initramfs.conf" ] || fail 'update-initramfs.conf already exists'
printf 'update_initramfs=no\n' >"$T/etc/initramfs-tools/update-initramfs.conf"
install -d "$T/var/cache/piano-install"
cp "$IN"/debs/*.deb "$T/var/cache/piano-install/"
chroot "$T" /usr/bin/env SYSTEMD_OFFLINE=1 DEBIAN_FRONTEND=noninteractive \
	/bin/sh -c 'dpkg --install /var/cache/piano-install/*.deb' </dev/null
audit=$(chroot "$T" dpkg --audit)
[ -z "$audit" ] || fail "dpkg --audit: $audit"
rm -r "$T/var/cache/piano-install"

step system locale
# Set the system/greeter default only. Ubuntu GDM's PAM stack reads the
# user's ~/.pam_environment (written by AccountsService/Initial Setup) later.
# Do not force LANGUAGE or LC_ALL in GDM or the user environment.
chroot "$T" locale-gen --keep-existing zh_CN.UTF-8 en_US.UTF-8
chroot "$T" update-locale --reset LANG=zh_CN.UTF-8
chroot "$T" locale -a >"$OUT/locales.txt"
cp "$T/etc/locale.conf" "$OUT/locale.conf"

step distribution kernels
# Only the piano kernel boots this tablet.  The base's generic HWE kernel and
# kdump (no crashkernel) would make every update download, rebuild initrds
# for and keep a kernel that never boots.  Purge their packages with what
# apt then no longer needs, keeping linux-firmware, which is not tied to a
# kernel.  Still within policy-rc.d and update_initramfs=no.
chroot "$T" dpkg-query -W -f '${db:Status-Abbrev}|${Package}|${Version}|${Architecture}\n' \
	>"$OUT/dpkg-query-base.txt"
kernels=$(chroot "$T" dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' | awk '
	$1 != "ii" { next }
	$2 ~ /^linux-(generic|image-generic|headers-generic|tools-generic)/ ||
	$2 ~ /^linux-(image|image-unsigned|modules|modules-extra|main-modules-[a-z0-9]+|headers|tools)-[0-9].*-generic$/ ||
	$2 == "kdump-tools" { print $2 }')
[ -n "$kernels" ] || fail 'no distribution kernel packages found'
echo "purging:" $kernels
df -B1 --output=used "$T" | tail -1 >"$OUT/used-bytes-before-purge.txt"
chroot "$T" apt-mark manual linux-firmware
# shellcheck disable=SC2086 # one word per package name
chroot "$T" /usr/bin/env SYSTEMD_OFFLINE=1 DEBIAN_FRONTEND=noninteractive \
	apt-get --yes --purge --autoremove remove $kernels </dev/null
df -B1 --output=used "$T" | tail -1 >"$OUT/used-bytes-after-purge.txt"
audit=$(chroot "$T" dpkg --audit)
[ -z "$audit" ] || fail "dpkg --audit after the purge: $audit"
left=$(chroot "$T" dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' 'linux-image-*' 'linux-modules-*' \
	'linux-headers-*' 'kdump-tools' 2>/dev/null | awk 'substr($1, 2, 1) != "n" && $2 != "linux-image-'"$RELEASE"'" { print $2 }')
[ -z "$left" ] || fail "kernel packages left besides linux-image-$RELEASE: $left"
chroot "$T" apt-get --simulate autoremove </dev/null >"$OUT/autoremove-simulate.txt"
! grep '^Remv ' "$OUT/autoremove-simulate.txt" || fail 'apt autoremove would still remove packages'
others=$(cd "$T/boot" && ls | grep -v -x -e "vmlinuz-$RELEASE" -e "initrd.img-$RELEASE" -e "config-$RELEASE" \
	-e "System.map-$RELEASE" -e vmlinuz -e initrd.img -e vmlinuz.old -e initrd.img.old || true)
[ -z "$others" ] || fail "/boot has files of another kernel: $others"
# linux-update-symlinks points the .old links at the remaining kernel.
for link in vmlinuz vmlinuz.old initrd.img initrd.img.old; do
	[ ! -L "$T/boot/$link" ] || [ "$(readlink "$T/boot/$link")" = "${link%.old}-$RELEASE" ] ||
		fail "/boot/$link points to $(readlink "$T/boot/$link")"
done
[ "$(ls "$T/usr/lib/modules")" = "$RELEASE" ] || fail "/usr/lib/modules has another kernel: $(ls "$T/usr/lib/modules")"
rm "$T/usr/sbin/policy-rc.d" "$T/etc/initramfs-tools/update-initramfs.conf"
[ -f "$T/boot/initrd.img-$RELEASE" ] || fail "no initrd for $RELEASE"

step services
# OpenSSH stays installed for developer mode, which is off; its own socket is
# disabled as on the test unit (docs/AGENT-GUIDE.md section 7.1).
systemctl --root="$T" disable ssh.socket ssh.service

step release boot set
mkdir -p "$T/run/piano-release" "$T/var/lib/piano/switch"
cp "$IN/release/boot-profile.json" "$IN/release/boot-signing.pem" "$T/run/piano-release/"
chroot "$T" python3 /usr/lib/piano/boot/build-persistent-boot.py \
	--kernel "/boot/vmlinuz-$RELEASE" --kernel-release "$RELEASE" \
	--dtb "/usr/lib/linux-image-$RELEASE/piano-boot.dtb" --initrd "/boot/initrd.img-$RELEASE" \
	--profile /run/piano-release/boot-profile.json --root-partlabel "$ROOT_PARTLABEL" --no-serial \
	--mkbootimg /usr/lib/piano/boot/mkbootimg.py --avbtool /usr/lib/piano/boot/avbtool.py \
	--key /run/piano-release/boot-signing.pem --output /var/lib/piano/switch/ubuntu
rm -r "$T/run/piano-release"
(cd "$T/var/lib/piano/switch/ubuntu" && sha256sum -c SHA256SUMS)

step per-machine state
# Created at the first boot or by developer mode (ssh-keygen -A), never shipped.
rm -f "$T"/etc/ssh/ssh_host_*
if [ -s "$T/etc/machine-id" ]; then
	echo 'NOTE: /etc/machine-id had content; emptied'
	: >"$T/etc/machine-id"
fi
rm -f "$T/var/lib/systemd/random-seed" "$T/var/lib/systemd/credential.secret"
rm -f "$T"/var/cache/apt/*.bin "$T"/var/cache/apt/archives/*.deb
# The base's package indexes are those of the build machine's mirror
# (archive.ubuntu.com), not of the Ports sources installed above; without
# them the first apt run needs `apt update` instead of finding nothing.
find "$T/var/lib/apt/lists" -mindepth 1 -maxdepth 1 -type f ! -name lock -delete
# Discard the free blocks (the purged kernels, dpkg and dracut leftovers keep
# their old content): the host punches them out of the image file
# (discard=unmap), and sparse_image.py writes only zero free blocks as DONT_CARE.
fstrim -v "$T"
rm -rf "$T"/var/log/journal/*

step report
chroot "$T" dpkg-query -W -f '${db:Status-Abbrev}|${Package}|${Version}|${Architecture}\n' >"$OUT/dpkg-query.txt"
for u in piano-devmode.service piano-devmode-ssh.socket ssh.socket ssh.service piano-slot-success.service \
		piano-debug.service piano-debug-timeout.service gdm.service; do
	echo "$u $(systemctl --root="$T" is-enabled "$u" 2>/dev/null || true)"
done >"$OUT/units.txt"
mkdir "$OUT/ubuntu-set"
cp "$T"/var/lib/piano/switch/ubuntu/* "$OUT/ubuntu-set/"
(cd "$T" && ls -ln boot etc/piano var/lib/piano/switch var/lib/piano/switch/ubuntu home etc/ssh) >"$OUT/listing.txt"
chroot "$T" sh -c 'sha256sum /boot/vmlinuz-'"$RELEASE"' /boot/initrd.img-'"$RELEASE"' /usr/lib/linux-image-'"$RELEASE"'/piano-boot.dtb' >"$OUT/boot-files.sha256"
echo PIANO_ROOTFS_GUEST_DONE
