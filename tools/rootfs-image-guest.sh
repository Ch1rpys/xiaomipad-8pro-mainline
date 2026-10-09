#!/bin/sh
# SPDX-License-Identifier: MIT
# Guest half of build-rootfs-image.py: runs as root in a disposable QEMU ARM64
# guest whose own root is the read-only pristine Desktop SquashFS.  It applies
# docs/AGENT-GUIDE.md section 4.4 to the target ext4 on a second disk: image
# policy, /etc/piano/layout.json and fstab, then dpkg --install in a chroot
# with policy-rc.d and SYSTEMD_OFFLINE=1, so the distribution kernel hooks run
# dracut and the piano hooks inside the target.  It then builds the release
# boot image set into the store and removes per-machine state.  The target
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
