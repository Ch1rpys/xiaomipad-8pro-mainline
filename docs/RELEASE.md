# Release artefacts

How a release directory (v0.1.0-preview and later) is built from pinned inputs, what it contains,
what each owner adds, and how it is installed. The tools write local files only: nothing is uploaded,
no GitHub release is created and no tablet is accessed. No release has been published yet.

## Contents

| Path in the release directory | Content |
|---|---|
| `boot/boot.img`, `boot/init_boot.img`, `boot/vendor_boot.img` | Ubuntu boot image set for slot A, AVB-signed with a release key; `boot/SHA256SUMS` lists them |
| `boot/boot-ram-check.img` | v2 image with the same kernel, initrd, DTB and command line, for `fastboot boot` before writing slot A |
| `boot/boot-ram-maintenance.img`, `boot/maintenance-manifest.json` | v2 RAM image with the same kernel and DTB and the maintenance initramfs: a root shell over USB with nothing mounted, for writing the partition table ([INSTALL.md step 6](INSTALL.md#6-write-the-partition-table-on-the-tablet)); its inputs and command line |
| `boot/manifest.json`, `boot/boot-profile.json`, `boot/piano-boot.dtb` | set inputs and outputs; the boot profile holds only stock-build fields; the DTB the set carries |
| `rootfs/root.sparse.img` | the 60 GiB `linux_rootfs` ext4 as an Android sparse image, for `fastboot flash linux_rootfs` |
| `rootfs/manifest.json`, `rootfs/verification.json`, `rootfs/qemu-boot-check.json` | every input hash and package version; the offline checks; the QEMU boot result |
| `debs/` | the piano packages installed in the image: `linux-image-<release>`, `piano-device-support`, `piano-local-firmware`, `piano-mesa`, `piano-ubuntu-desktop` |
| `tools/piano-switch.py`, `tools/piano-switch-ksu-<version>.zip` | host Fastboot switching and recovery; the Android KernelSU module (not yet verified on the device) |
| `RELEASE-NOTES.md`, `release-manifest.json`, `SHA256SUMS` | generated from `packaging/release/RELEASE-NOTES.md.in`; release identity and checks; every file |

The `linux_data` (`/home`) filesystem is not shipped; it is created at install time (below).

## What the image contains

- Ubuntu 26.04 Desktop ARM64 (the two official ISO layers merged unchanged, [build.zh-CN.md](build.zh-CN.md)),
  with the APT sources of [ubuntu/26.04.sources](../ubuntu/26.04.sources), cloud-init disabled and the
  CD-ROM source removed (the policy of `build-ubuntu-ext4.py`).
- The piano packages above, `openssh-server` for developer mode, and the updated `dracut`, all
  installed by `dpkg --install` in a chroot with `policy-rc.d` and `SYSTEMD_OFFLINE=1`
  ([AGENT-GUIDE.md](AGENT-GUIDE.md) §4.4). The kernel postinst runs Ubuntu's dracut hook
  (initrd with the `99piano` module) and the piano hook.
- `/etc/fstab` and `/etc/piano/layout.json` naming the fixed GPT partitions, so the image fits any unit:
  ```
  PARTLABEL=linux_rootfs / ext4 defaults,noatime 0 1
  PARTLABEL=linux_data /home ext4 defaults,noatime 0 2
  ```
- The boot set in `/var/lib/piano/switch/ubuntu/`, the same files as `boot/`.

It has no user account (GNOME Initial Setup creates the first one; GDM has no automatic login), an
empty `/etc/machine-id`, no SSH host keys (developer mode creates them), Ubuntu's `ssh.socket` and
developer mode off, no journal or APT caches, and no file of any unit in `/etc/piano`.

The boot set is address-free: `build-persistent-boot.py --root-partlabel linux_rootfs --no-serial`
without `--bt-address-file` or `--wlan-address-file`. Its command line is

```
root=PARTLABEL=linux_rootfs rootfstype=ext4 rw rootwait console=ttyMSM0,115200n8 log_buf_len=2M panic=15
msm.separate_gpu_kms=1 piano.boot=persistent systemd.gpt_auto=0 bootconfig
```

ABL appends `androidboot.serialno` and its other parameters itself, as on every boot. The DTB has
no `local-bd-address` or `local-mac-address` property. The boot profile keeps only the fields of
the stock build (header version, partition sizes, rollback indices, AVB properties, `vendor_boot`
page size and load addresses).

## Per-unit and per-build inputs

| Input | Scope | Where it goes | Without it |
|---|---|---|---|
| `bluetooth-address` | this unit | `/etc/piano/` | the Bluetooth controller stays unconfigured |
| `wlan-address` | this unit (`wlan/wlan_mac.bin` on `persist`) | `/etc/piano/` | a random Wi-Fi MAC address on every boot: the WCN7860 reports an all-zero address and ath12k (7.2.6-piano4 and later) falls back to a random one unless the boot DTB carries the address |
| `thp-calibration.json` | this unit's panel | `/etc/piano/` | no touch input |
| `boot-profile.json` | this unit (`serial`) and its stock build (the rest) | `/etc/piano/` | `piano-boot-update` keeps the prebuilt set; `piano-boot-switch` refuses |
| `boot-signing.pem` | the owner | `/etc/piano/` | `piano-boot-update` keeps the prebuilt set |
| `boot-partitions.json` | this unit's GPT | `/etc/piano/` | `piano-boot-switch` refuses |
| Android set (`boot_a`, root-patched `init_boot_a`, `vendor_boot_a`) | this unit | `/var/lib/piano/switch/android/` | switching to Android from Ubuntu is refused; use Fastboot |
| stock base DTB (`vendor_boot_a`) and DTBO entry (`dtbo_a`) | the stock build | `prepare-boot-dtb.py`, then the kernel package | needed only to build a kernel package |

[AGENT-GUIDE.md](AGENT-GUIDE.md) §4.3 shows how to obtain each one. The prebuilt set and the
`piano-boot.dtb` in the kernel package were made from the stock build OS3.0.303.0.WPYCNXM; with
another stock build, prepare the DTB and the set from your own images.

## Building a release

Host tools, none run as root: `dpkg-deb`, `python3-debian`, `img2simg`, `sgdisk`, `openssl`, `zip`,
QEMU `qemu-system-aarch64` (TCG), squashfs-tools-ng 1.2 `sqfs2tar`, and e2fsprogs 1.47.4
`mke2fs`/`e2fsck`/`debugfs` built with libarchive (the identity is recorded in the manifests).

```bash
# 1. Ubuntu packages added to the base, from a signed snapshot
python3 tools/prepare-ubuntu-apt.py --rootfs out/ubuntu-desktop-pristine/ubuntu-desktop.squashfs \
  --snapshot 20261001T000000Z --output out/apt-release --download dracut device-tree-compiler openssh-server
# 2. The piano packages (AGENT-GUIDE.md §3.4, §3.5)
# 3. The root image and the boot set; about 35 minutes, most of it in the QEMU guest
python3 tools/build-rootfs-image.py \
  --squashfs out/ubuntu-desktop-pristine/ubuntu-desktop.squashfs --squashfs-sha256 <sha256> \
  --sqfs2tar <sqfs2tar> --mke2fs <mke2fs> --mke2fs-config <mke2fs.conf> --e2fsck <e2fsck> --debugfs <debugfs> \
  --qemu <qemu-system-aarch64> --kernel-deb out/kernel-deb-<N>/linux-image-<release>_*.deb \
  --deb <piano-device-support.deb> --deb <piano-local-firmware.deb> --deb <piano-mesa.deb> --deb <piano-ubuntu-desktop.deb> \
  --apt-manifest out/apt-release/manifest.json \
  --boot-profile <boot-profile.json read from a stock unit> --boot-key <release signing key> \
  --output out/rootfs-<version>
# expect "state": "ROOT_IMAGE_BUILT_OFFLINE_CHECKS_PASS_NOT_BOOTED"
# 4. Boot the image in QEMU towards multi-user.target (optional; under TCG, snap seeding exceeds 20 minutes)
python3 tools/check-rootfs-boot.py --rootfs-build out/rootfs-<version> --qemu <qemu-system-aarch64> \
  --debugfs <debugfs> --mke2fs <mke2fs> --output out/rootfs-<version>-boot
# 5. The maintenance RAM image of the same kernel package (AGENT-GUIDE.md §4.6), address-free
python3 tools/build-persistent-boot.py --maintenance --no-serial --kernel <vmlinuz-<release>> \
  --kernel-release <release> --dtb <piano-boot.dtb of the package> --initrd out/maintenance-initramfs/initramfs.cpio.gz \
  --profile out/rootfs-<version>/boot-profile.json --mkbootimg tools/local/aosp-mkbootimg/mkbootimg.py \
  --output out/maintenance-ram-<version>
# 6. The release directory
python3 tools/build-release.py --rootfs-build out/rootfs-<version> \
  --boot-check out/rootfs-<version>-boot/result.json --maintenance out/maintenance-ram-<version> \
  --forbid-file <your bluetooth-address> --forbid-file <your wlan-address> --forbid-file <your boot-profile.json> \
  --output out/release-<version>
(cd out/release-<version> && sha256sum -c SHA256SUMS)
```

- `build-rootfs-image.py` streams the SquashFS through `sqfs2tar` into `mke2fs -d -` at the full
  partition size, then boots a QEMU ARM64 guest whose root is the same SquashFS, read-only. The guest
  runs [tools/rootfs-image-guest.sh](../tools/rootfs-image-guest.sh) as root on the target attached as
  a second disk, which never boots. The release key reaches the guest only on a temporary input disk
  and a tmpfs; the input disk is deleted afterwards.
- The boot profile you pass is reduced to the stock-build fields before use; the unit's serial,
  slot observations and image hashes are dropped and its hash is not recorded.
- The tool then runs `e2fsck -fn`, checks the finished image with `debugfs` (`verification.json`:
  packages, accounts, machine ID, SSH host keys, `/etc/piano`, fstab, units, kernel files, the store set,
  file capabilities), and writes `root.sparse.img`, `SHA256SUMS` and `manifest.json`. The image is not
  byte-reproducible: dpkg and dracut record times, and dracut initrds differ between runs.
- `--forbid-file` makes `build-release.py` scan every output for identifiers of your unit (serial,
  Bluetooth and Wi-Fi address in text and binary forms). The files are read, never copied or recorded;
  the scan does not see inside compressed files.
- `root.sparse.img` stores the zero blocks of the 60 GiB file as FILL chunks, which Fastboot writes in
  full (about 4 minutes on the test unit). `build-release.py` hard-links it, so the release directory
  must be on the same filesystem as the build.

## Installing the release

Manual in v0.1. The owner's step-by-step guide is [INSTALL.md](INSTALL.md); it follows
[AGENT-GUIDE.md](AGENT-GUIDE.md) §4 with these changes:

1. §4.1–§4.3 unchanged: prerequisites, backup, and your per-unit inputs.
2. §4.4 is replaced by the release files: no root build on the host. Create the data image for your
   `linux_data` size (`fastboot getvar partition-size:linux_data`):
   ```bash
   truncate -s <linux_data bytes> data.ext4
   mkfs.ext4 -L linux_data data.ext4 && img2simg data.ext4 data.sparse.img
   ```
3. §4.5–§4.6 unchanged (§4.6 in `boot/boot-ram-maintenance.img`), except that the GUIDs of `linux_rootfs` and `linux_data` may be any new
   values: the release finds both partitions by name. The names must be exactly `linux_rootfs` and
   `linux_data`.
4. §4.7 with `rootfs/root.sparse.img` for `linux_rootfs` and `data.sparse.img` for `linux_data`.
5. Optionally `fastboot -s <SERIAL> boot boot/boot-ram-check.img` to check the installed root before
   writing slot A (a normal boot without a debug console; it returns to Fastboot only by Power + Volume Down).
6. §4.9 from the host: `python3 tools/piano-switch.py --serial <SERIAL> --images boot --rollback <android-set>`,
   then `fastboot -s <SERIAL> reboot`. GNOME Initial Setup creates the first account; the slot is
   marked successful after the boot (the release set is in the store).
7. In Ubuntu, install your files (root, mode 0600) and the Android set, then rebuild the boot set:
   ```bash
   sudo install -m 600 bluetooth-address wlan-address thp-calibration.json boot-profile.json \
     boot-signing.pem boot-partitions.json /etc/piano/          # boot-partitions.json: §4.8
   sudo piano-boot-switch import-android --from <android-set>
   sudo piano-boot-update <release>
   # expect "Piano boot image set prepared for <release>" and "Slot A now holds store/ubuntu"
   ```
   The new set carries your addresses, serial and key; the release set becomes `ubuntu.prev`.
   Reboot, then `sudo piano-boot-switch verify`.

Until step 7, Bluetooth, touch and switching from Ubuntu are unavailable, Wi-Fi uses a random MAC
address, and kernel package updates leave the boot set unchanged. Use the magnetic keyboard for Initial Setup.

## Verification status

- v0.1.0-preview is built from 7.2.6-piano5. Its offline checks (`rootfs/verification.json`) and the
  identity scan cover the image and the boot set as files.
- On the test unit, 7.2.6-piano4 booted as a RAM boot with the partition-name root and the
  serial-free command line of an address-free set, and the random Wi-Fi MAC fallback worked; Wi-Fi
  scanning found 2.4 GHz and 5 GHz networks.
- QEMU: no boot was run for the piano5 build. An earlier build of the same pipeline with
  7.2.6-piano3 (TCG, `apparmor=0`, 20 minutes) found and checked `linux_rootfs` by name and mounted
  `/home` from `linux_data`; the only failed unit was `piano-slot-success` (expected: QEMU is not
  piano), and `multi-user.target` was still waiting for Ubuntu's first-boot `snapd.seeded.service`.
- On the test unit (2026-10-10), `boot/boot-ram-maintenance.img` (`21f3a043…`, 7.2.6-piano5,
  serial-free) booted from RAM: NCM link after 4 s, six LUNs, LUN 0's `sgdisk -p`, `sfdisk --json` and
  `sgdisk --verify` matching the installed table, nothing mounted, and the idle timer rebooted it
  into Fastboot by itself. No write was run from it.
- The release image as a whole has not been flashed to a tablet.
