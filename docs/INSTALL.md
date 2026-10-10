# Installing v0.1.0-preview

[中文](INSTALL.zh-CN.md) | [Project overview](../README.md) | [Fastboot, switching and recovery](FLASHING.md)

This guide installs a v0.1.0-preview release next to Android on the Xiaomi Pad 8 Pro (`piano`) by
hand. Installation is manual in v0.1: there is no installer yet. Writing the new partition table
([step 6](#6-write-the-partition-table-on-the-tablet)) runs in the release's maintenance RAM image.
Read the whole guide before you start.

## Read first

- **All Android data is erased.** `userdata` is shrunk and re-created, `metadata` is cleared.
- **One tested unit.** Model 25091RP04C (China), 512 GB UFS, stock build `OS3.0.303.0.WPYCNXM` on
  slot A. Other models, capacities and stock builds are untested; the prebuilt boot set fits
  `OS3.0.303.0.WPYCNXM` only.
- **The bootloader must be unlocked** through Xiaomi's official process.
- **Back up first** ([step 2](#2-back-up)). Your stock slot A images are your way back to Android.
- **No charging under Linux.** Charge in Android and leave Android with at least 40 %.
- **Never flash `vbmeta`, `dtbo`, any `_b` partition, `persist` or other calibration, modem or
  firmware partitions, and never run `fastboot --set-active=b`.** Slot B on the test unit holds an
  older stock chain that does not boot Android.
- **Keep the tablet attended.** Power + Volume Down enters Fastboot from any state; release images
  have no debug console.
- **Put the serial on every command** (`adb -s <SERIAL>`, `fastboot -s <SERIAL>`,
  `piano-switch.py --serial <SERIAL>`) and run only one tool against the tablet at a time.
- **On a failure, stop.** Do not repeat a write after one failed status query, do not re-flash a
  partition that was written successfully, and do not interrupt a write that is still running.

Steps that use standard commands because no project tool exists yet are marked *manual*.

## What you need

| Item | Notes |
|---|---|
| Xiaomi Pad 8 Pro on stock `OS3.0.303.0.WPYCNXM`, slot A active | `adb` reachable in Android |
| Root in Android | Magisk or KernelSU-Next in a patched `init_boot_a`, to read partitions (*manual*, follow that project's instructions) |
| Xiaomi magnetic keyboard | the only input until your touch calibration is installed ([step 10](#10-install-your-units-files)) |
| Linux x86_64 host | Android platform-tools (`adb`, `fastboot`), Python 3, `openssl`, `uuidgen`, `sgdisk`, `sfdisk`, `losetup`, `mkfs.ext4`, `img2simg`, `sha256sum`, `telnet`, `nc` (OpenBSD netcat) |
| AOSP `avbtool.py` | from AOSP `external/avb` (no fetch script yet) |
| This repository | checked out at the integration commit in the release's `RELEASE-NOTES.md`; then `sh tools/fetch-aosp-mkbootimg.sh` |
| The release directory | every file of one release, not mixed with other releases |
| Free host space | about 40 GB: the backup (16 GB on the test unit), the release (about 9 GB) and the data image |

Download every `piano-v0.1.0-preview.tar.zst.part*` of the [release](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.1.0-preview) into one directory, restore
the release directory (about 14 GB of free space) and check it before using it:

```bash
sha256sum -c SHA256SUMS.assets                   # the downloaded files
cat piano-v0.1.0-preview.tar.zst.part* | zstd -d | tar -x
cd <release> && sha256sum -c SHA256SUMS          # expect every line "OK"
```

The release contains `boot/` (the Ubuntu boot set for slot A, `boot-ram-check.img` and
`boot-ram-maintenance.img`),
`rootfs/root.sparse.img` (the 60 GiB root), `debs/`, `tools/piano-switch.py` and the KernelSU module.
Its contents are described in [RELEASE.md](RELEASE.md).

## 1. Unlock and check the stock build

Unlock the bootloader with Xiaomi's official tool (this erases the tablet), install the stock build
if needed, and root Android. Then:

```bash
adb -s <SERIAL> shell getprop ro.product.device              # expect "piano"
adb -s <SERIAL> shell getprop ro.build.version.incremental   # expect "OS3.0.303.0.WPYCNXM"
adb -s <SERIAL> shell getprop ro.boot.slot_suffix            # expect "_a"
adb -s <SERIAL> shell su -c id                               # expect "uid=0(root) ..."
adb -s <SERIAL> shell dumpsys battery | grep level           # expect 40 or higher
adb -s <SERIAL> reboot bootloader
fastboot -s <SERIAL> getvar unlocked                         # expect "unlocked: yes"
fastboot -s <SERIAL> getvar current-slot                     # expect "current-slot: a"
fastboot -s <SERIAL> reboot
```

Stop if any value differs.

## 2. Back up

*Manual.* Back up every partition except `userdata`, and the partition tables of every UFS LUN. Use
`adb exec-out` (binary-safe), not `adb shell`, for image data. Keep the backup outside the repository.

```bash
mkdir -p backup/gpt
adb -s <SERIAL> shell su -c 'for d in /sys/block/sd?; do echo ${d##*/} $(cat $d/size) $(cat $d/queue/logical_block_size); done'
# expect six LUNs with logical block size 4096; size is in 512-byte units
adb -s <SERIAL> shell su -c 'ls -l /dev/block/by-name/'     # label -> /dev/block/sdXN

# for each partition label except userdata
adb -s <SERIAL> exec-out su -c 'dd if=/dev/block/by-name/<label> bs=1048576 2>/dev/null' > backup/<label>.img
adb -s <SERIAL> shell su -c 'sha256sum /dev/block/by-name/<label>'    # must equal the next line
sha256sum backup/<label>.img

# for each LUN sdX: MBR and primary GPT, backup GPT; <blocks> = size / 8
adb -s <SERIAL> exec-out su -c 'dd if=/dev/block/sdX bs=4096 count=34 2>/dev/null' > backup/gpt/sdX-head.bin
adb -s <SERIAL> exec-out su -c 'dd if=/dev/block/sdX bs=4096 skip=<blocks-34> 2>/dev/null' > backup/gpt/sdX-tail.bin
```

- Write down a manifest: label, device node, LUN, size and SHA-256 of each file, and each LUN's disk
  GUID. `sdX` names change between boots; only this manifest maps files to partitions.
- `persist` and `metadata` are mounted read-write by Android and can change while you read them:
  hash twice and repeat the read if the hashes differ.

Make the **Android image set** from the backup. `init_boot` must be the root-patched image that is
in slot A now:

```bash
mkdir android-set
cp backup/boot_a.img android-set/boot.img
cp backup/init_boot_a.img android-set/init_boot.img
cp backup/vendor_boot_a.img android-set/vendor_boot.img
(cd android-set && sha256sum boot.img init_boot.img vendor_boot.img > SHA256SUMS)
```

Keep `android-set/` and a copy of the release's `boot/` on the host: they are the two sets used for
switching and recovery ([FLASHING.md](FLASHING.md)).

## 3. Collect your unit's files

These files belong to your tablet. Never share or commit them, and never use another tablet's.
They are installed in Ubuntu in [step 10](#10-install-your-units-files).

| File | Without it |
|---|---|
| `thp-calibration.json` | no touch input |
| `bluetooth-address` | the Bluetooth controller stays unconfigured |
| `wlan-address` | Wi-Fi uses a random MAC address on every boot |
| `boot-profile.json`, `boot-signing.pem` | the boot set cannot be rebuilt: the addresses are not applied and kernel updates leave slot A unchanged |
| `boot-partitions.json` (made in step 8a or 10) | `piano-boot-switch` refuses to switch, and kernel and initrd updates leave the boot set and slot A unchanged |

**Touch calibration.** The stock ODM partition holds `piano_nova_csot_thp_config.ini` (CSOT panel,
as on the test unit) and `piano_nova_boe_thp_config.ini`. Use the one your stock driver loads; on the
test unit the stock kernel log names the CSOT file.

```bash
adb -s <SERIAL> shell su -c 'find /odm -name "piano_nova_*_thp_config.ini"'
adb -s <SERIAL> exec-out su -c 'cat <path to the ini>' > thp.ini
python3 tools/extract-thp-calibration.py --input thp.ini --output thp-calibration.json
```

**Bluetooth address.**

```bash
adb -s <SERIAL> shell settings get secure bluetooth_address > bluetooth-address
cat bluetooth-address                  # expect one XX:XX:XX:XX:XX:XX line
```

**Wi-Fi address** (*manual*). The stock address is the line `wlan0=<12 hex digits>` in
`wlan/wlan_mac.bin` on `persist`; Android links it from the WLAN firmware directory. Convert it to
`XX:XX:XX:XX:XX:XX`:

```bash
adb -s <SERIAL> exec-out su -c 'cat /vendor/firmware/wlan/qca_cld/peach_v2/wlan_mac.bin' \
  | sed -n 's/^wlan0=\(..\)\(..\)\(..\)\(..\)\(..\)\(..\).*/\1:\2:\3:\4:\5:\6/p' > wlan-address
cat wlan-address                       # expect one XX:XX:XX:XX:XX:XX line
```

**Signing key.** Your own AVB key for the boot sets you build:

```bash
openssl genrsa -out boot-signing.pem 4096
```

**Boot profile** (*manual*, no generator yet). ABL marks the slot unbootable unless the boot images
carry the stock header fields, rollback indices and AVB properties. Write `boot-profile.json` with the
values of your stock images:

```
{
  "serial": "<SERIAL>",
  "boot":        {"header_version": 4, "capacity": 100663296, "rollback_index": <int>, "avb_properties": {<props>}},
  "init_boot":   {"header_version": 4, "capacity": 8388608,   "rollback_index": <int>, "avb_properties": {<props>}},
  "vendor_boot": {"header_version": 4, "capacity": 100663296, "rollback_index": <int>, "avb_properties": {<props>},
                  "page_size": <int>, "kernel_addr": <int>, "ramdisk_addr": <int>, "tags_addr": <int>, "dtb_addr": <int>}
}
```

```bash
python3 tools/local/aosp-mkbootimg/unpack_bootimg.py --boot_img backup/vendor_boot_a.img --out /tmp/vb
# header version, page size, kernel, ramdisk and tags load addresses, dtb address
python3 <avbtool.py> info_image --image backup/boot_a.img
# "Rollback Index:" and every "Prop: com.android.build.boot.*" line; repeat for init_boot_a and vendor_boot_a
```

`capacity` is the partition size in bytes. Copy every `Prop:` of each image into its
`avb_properties`; `boot` needs at least `com.android.build.boot.os_version` and
`com.android.build.boot.security_patch`. The release's `boot/boot-profile.json` shows the same
structure for the stock build, without a serial.

## 4. Partition layout

The original `userdata` range on LUN 0 is split into three partitions. All other partitions and
LUNs stay unchanged.

| Entry | Name | Size (512 GB unit) | Use |
|---|---|---|---|
| 34 | `userdata` | 200 GiB | Android data; keeps its start, type GUID, unique GUID and attributes |
| 35 | `linux_rootfs` | 60 GiB | Ubuntu `/` |
| 36 | `linux_data` | the remainder, about 201.27 GiB | Ubuntu `/home` |

The release finds its partitions by name: the names must be exactly `linux_rootfs` and
`linux_data`. Their GUIDs can be any new values.

## 5. Build the new partition table (host)

*Manual.* Work on a copy of LUN 0's table, never on the tablet. LUN 0 has 4096-byte blocks
(124,552,192 on the 512 GB unit).

```bash
ROOT_UUID=$(uuidgen); DATA_UUID=$(uuidgen)
BLOCKS=<LUN 0 size / 8>                         # from step 2
truncate -s $((BLOCKS * 4096)) lun0.img
dd if=backup/gpt/<lun0>-head.bin of=lun0.img bs=4096 conv=notrunc
dd if=backup/gpt/<lun0>-tail.bin of=lun0.img bs=4096 seek=$((BLOCKS - 34)) conv=notrunc
LOOP=$(sudo losetup --find --show --sector-size 4096 lun0.img)
sudo sgdisk --print "$LOOP"       # expect "Sector size (logical): 4096 bytes" and your table
sudo sgdisk --info=34 "$LOOP"     # expect "Partition name: 'userdata'"; note first sector, type GUID, unique GUID, attributes
sudo sfdisk --json "$LOOP" > gpt-before.json

S=<first sector of userdata>      # 3632128 on the test unit
U=<unique GUID of userdata>; T=<type GUID of userdata>
L=0FC63DAF-8483-4772-8E79-3D69D8477DE4      # Linux filesystem
sudo sgdisk --set-alignment=256 --delete=34 \
  --new=34:$S:$((S + 52428800 - 1)) --typecode=34:$T --partition-guid=34:$U --change-name=34:userdata \
  --new=35:$((S + 52428800)):$((S + 68157440 - 1)) --typecode=35:$L --partition-guid=35:$ROOT_UUID --change-name=35:linux_rootfs \
  --new=36:$((S + 68157440)):0 --typecode=36:$L --partition-guid=36:$DATA_UUID --change-name=36:linux_data \
  "$LOOP"
sudo sgdisk --verify "$LOOP"      # expect "No problems found."
sudo sfdisk --json "$LOOP" > gpt-after.json
```

Compare `gpt-before.json` and `gpt-after.json`: only entries 34–36 may differ, starting at `S`,
`S + 52428800` and `S + 68157440`. The disk GUID, first and last usable LBA and table length must
not change. If `userdata` had non-zero attributes, copy them with `--attributes=34:=:<hex>`.

Extract the two table regions (first usable LBA 6 and last usable LBA 124552186 on the test unit):

```bash
FIRST=<first usable LBA>; LAST=<last usable LBA>        # from sgdisk --print
sudo dd if="$LOOP" of=new-primary.bin bs=4096 count=$FIRST
sudo dd if="$LOOP" of=new-backup.bin bs=4096 skip=$((LAST + 1))
dd if=backup/gpt/<lun0>-head.bin bs=4096 count=$FIRST 2>/dev/null | sha256sum    # current primary region
sha256sum new-primary.bin new-backup.bin
sudo losetup -d "$LOOP"
```

## 6. Write the partition table (on the tablet)

*Manual commands in a project environment.* `boot/boot-ram-maintenance.img` starts the release
kernel from RAM with a small initramfs: the UFS driver, a root shell over the USB cable
(192.168.88.2, telnet port 2323, no password; the link carries only this cable) and the tools of
this step (`sgdisk`, `sfdisk`, `lsblk`, `partx`, `blockdev`, `dd`, `sha256sum`, `wget`). It mounts
no partition of any UFS disk and writes nothing by itself; slot A keeps Android. With no open
session for 10 minutes (also after the cable is pulled), it reboots into Fastboot.

On the host, with the tablet in Fastboot and `new-primary.bin` and `new-backup.bin` of step 5 in
the current directory:

```bash
fastboot -s <SERIAL> boot <release>/boot/boot-ram-maintenance.img    # expect "Booting OKAY"
python3 tools/piano-devmode-ssh.py --serial <SERIAL> --check         # expect "... 192.168.88.10 -> 192.168.88.2 ready" (about 5 s)
python3 -m http.server --bind 192.168.88.10 8000 &                    # serves the two files to the tablet
telnet 192.168.88.2 2323
```

Start `http.server` after `--check` reports the link: the address 192.168.88.10 exists only while the
link is up (`Cannot assign requested address` otherwise). If it reports `Address already in use`, another
server holds the port, possibly on every address; use a free port in the `wget` lines below. The hash
checks of the downloaded files catch a wrong server.

If `--check` prints `ip` commands instead, run them and check again. The login prints the LUN
table (LUN, disk, size in 512-byte sectors, block size, device path), `Mounted from the UFS
disks: none` and the `sgdisk -p` table of LUN 0. LUN 0 is the line starting with `0`, size
996417536 and block size 4096 on the 512 GB unit; check that the table is your table of step 2.
Then, in the telnet session:

```sh
FIRST=<first usable LBA>; LAST=<last usable LBA>; BLOCKS=<LUN 0 blocks>    # the values of step 5
disk=/dev/sdX                                           # LUN 0 from the login table
piano-maint map                                         # again: "LUN 0: /dev/sdX", "Mounted from the UFS disks: none"
wget -O /run/new-primary.bin http://192.168.88.10:8000/new-primary.bin
wget -O /run/new-backup.bin http://192.168.88.10:8000/new-backup.bin
sha256sum /run/new-primary.bin /run/new-backup.bin      # expect the hashes of step 5
dd if=$disk bs=4096 count=$FIRST | sha256sum            # expect the current primary region hash of step 5
dd if=/run/new-backup.bin of=$disk bs=4096 seek=$((LAST + 1)) conv=fsync
dd if=$disk bs=4096 skip=$((LAST + 1)) count=$((BLOCKS - LAST - 1)) | sha256sum   # expect new-backup.bin
dd if=/run/new-primary.bin of=$disk bs=4096 conv=fsync
dd if=$disk bs=4096 count=$FIRST | sha256sum            # expect new-primary.bin
sync
sgdisk --verify $disk                                   # expect "No problems found."
sgdisk -p $disk                                         # expect entries 34-36 userdata, linux_rootfs, linux_data
piano-maint fastboot                                    # reboots into Fastboot
```

Write the backup copy first, then the primary, and compare each readback before continuing. The
kernel keeps the old partition list until the reboot; do not mount or format anything in this
session. Stop the host's `http.server` afterwards.

- `piano-maint status` shows the idle count; `piano-maint keepalive` restarts it and
  `piano-maint idle SECONDS` (30–3600) changes the limit. An open telnet session holds the
  timer only while the cable is connected.
- If `piano-maint fastboot` says `nvmem-reboot-mode is not bound`, it does not reboot; use
  Power + Volume Down.
- Verified on the test unit (2026-10-10): boot, link after about 4 s, LUN table, `sgdisk -p`,
  `sfdisk --json` and `sgdisk --verify` of LUN 0 matching the table written on 2026-10-07, nothing
  mounted, and the idle reboot into Fastboot. The write commands above wrote that table on
  2026-10-07 from an earlier RAM environment. From this image (2026-10-10) they rewrote the same
  table over itself: the region hashes before and after equal the stored files, both readbacks
  matched, `sgdisk --verify` found no problems and `piano-maint fastboot` returned to Fastboot; a
  changed table has not yet been written from this image.

## 7. Write the filesystems (Fastboot)

Check the new partitions, then create the `/home` image for your `linux_data` size:

```bash
fastboot -s <SERIAL> getvar partition-size:userdata       # expect "3200000000" (hex, printed without 0x)
fastboot -s <SERIAL> getvar partition-size:linux_rootfs   # expect "0xF00000000"
fastboot -s <SERIAL> getvar partition-size:linux_data     # "0x32517FB000" on the 512 GB unit
truncate -s $((0x<linux_data size>)) data.ext4
mkfs.ext4 -L linux_data data.ext4 && img2simg -s data.ext4 data.sparse.img     # about 6 MB
```

Erase Android's data and write both filesystems:

```bash
fastboot -s <SERIAL> erase userdata
fastboot -s <SERIAL> erase metadata
python3 tools/sparse_image.py summary <release>/rootfs/root.sparse.img data.sparse.img   # what the tablet will write
fastboot -s <SERIAL> flash linux_rootfs <release>/rootfs/root.sparse.img   # a few minutes; 8.7 to 10.1 GB written
fastboot -s <SERIAL> flash linux_data data.sparse.img                      # seconds
# expect "OKAY" on every Sending and Writing line, then "Finished."
```

The tablet writes the RAW and FILL blocks of a sparse image and skips its DONT_CARE blocks. The root
image writes only the blocks its filesystem uses (7.2.6-piano6 builds: 8.2 GiB of data and 1.1 GiB of
zeroed inode tables and journal, 10.1 GB in all; the 51 GiB of free space are DONT_CARE). From the
7.2.6-piano7 build the image build also discards the blocks it freed by removing Ubuntu's generic
kernels, about 8.7 GB in all (measured offline on a test build of that root); the `summary` line
above prints the figure of your image. `img2simg -s` likewise leaves the free blocks of
`data.sparse.img` out (6 MB of data, at most 1 GiB of journal fill).

**`OKAY` does not mean the write is finished.** The bootloader answers once the data has arrived and
keeps writing FILL blocks in the background at about 30 MB/s; the next Fastboot command waits until it
is done. Do not unplug the cable, reset or power off the tablet while a command waits, and do not
repeat a write that finished with `OKAY`. (On the test unit, 2026-10-10: an earlier image of this
preview stored the free space of the root as 51.8 GiB of FILL; `flash linux_rootfs` returned `OKAY`
after 41 s, and the following `flash linux_data` of a 6 MB image returned only after 1839 s, the root's
FILL commit. A data image with 1 GiB of FILL delayed the next `fastboot boot` by about 30 s.) Android
re-creates `userdata` and `metadata` on its next boot; all Android data, including the root manager's
configuration, is gone.

## 8. Optional: test-boot without writing slot A

```bash
fastboot -s <SERIAL> boot <release>/boot/boot-ram-check.img     # expect "Booting OKAY"
```

This boots the installed root once from RAM, with the same kernel, initrd and command line as the
release set, and writes no boot partition. It is a normal boot without a debug console: return to
Fastboot with Power + Volume Down.

## 8a. Recommended: install your unit's files before the first boot

The maintenance image of [step 6](#6-write-the-partition-table-on-the-tablet) can make the partition
map, put it with your touch calibration and addresses into the new root and turn on developer mode
before Ubuntu first boots. Touch then works in Initial Setup, and the host can reach the tablet over
SSH as soon as the account exists. Without this step, use the magnetic keyboard in Initial Setup and
copy the files in step 10.

Keep `boot-profile.json` and `boot-signing.pem` on the host until step 10. Initial Setup's keyboard
page rebuilds the initrd; with these two files in the root, the boot hook rebuilds the boot set and
writes slot A, which the v0.1.0-preview root's `piano-boot-switch` (0.1+20261010.3) refuses (step
10). The package configuration then fails and `dracut` stays half-configured.

In Fastboot, with the files of step 3 in the current directory on the host:

```bash
fastboot -s <SERIAL> boot <release>/boot/boot-ram-maintenance.img    # expect "Booting OKAY"
python3 tools/piano-devmode-ssh.py --serial <SERIAL> --check         # expect "... ready"
python3 -m http.server --bind 192.168.88.10 8000 &                    # a free port, as in step 6
telnet 192.168.88.2 2323
```

In a second terminal on the host, in the same directory, wait for the boot LUN's partition table:

```bash
nc -l 192.168.88.10 8001 | python3 tools/extract-boot-partitions.py --input - \
  --profile boot-profile.json --output boot-partitions.json
```

In the telnet session, send it (another free port works as well):

```sh
sfdisk --json /dev/sdY | nc 192.168.88.10 8001      # sdY: LUN 4 from the login table
```

The second terminal prints `init_boot_a` (8388608 B), `vendor_boot_a` and `boot_a` (100663296 B
each) and writes `boot-partitions.json`. The tool refuses a disk without `boot_a` and `boot_b`, and
sizes other than those in your boot profile; `piano-boot-switch` later refuses the map unless the
disk is LUN 4. Then, on the host:

```bash
sha256sum thp-calibration.json bluetooth-address wlan-address boot-partitions.json
```

and in the telnet session:

```sh
disk=/dev/sdX                                       # LUN 0 from the login table
for p in /sys/class/block/${disk##*/}*; do grep -qx PARTNAME=linux_rootfs $p/uevent && root=/dev/${p##*/}; done
echo $root                                          # entry 35 of LUN 0, for example /dev/sda35
mkdir -p /mnt && mount -t ext4 $root /mnt
for f in thp-calibration.json bluetooth-address wlan-address boot-partitions.json; do
  wget -O /mnt/etc/piano/$f http://192.168.88.10:8000/$f && chmod 600 /mnt/etc/piano/$f
done
sha256sum /mnt/etc/piano/*                          # the four hashes must equal the host's
mkdir -p /mnt/etc/systemd/system/usb-gadget.target.wants
ln -sf /usr/lib/systemd/system/piano-devmode.service /mnt/etc/systemd/system/usb-gadget.target.wants/
sync; umount /mnt
piano-maint fastboot
```

`lsblk` shows no partition labels in this environment; the loop above reads them from sysfs. The
symbolic link is what `piano-devmode on` creates. Verified on the test unit (2026-10-10) with the
five files of an earlier version of this step: the files landed with mode 600 and the host's hashes,
nothing stayed mounted, and the next boot of the release set ran touch with the calibration and
started developer mode. Making the map here has not yet run on the tablet; offline, the release's
BusyBox `nc` closed the connection at the end of the table, the host's `nc -l` then exited, and the
tool rebuilt the test unit's map from its LUN 4 GPT.

## 9. Write slot A and first boot

Check the battery, then write the release set into slot A. `piano-switch.py` checks the tablet and
both sets first, and writes the Android set back if a write fails:

```bash
fastboot -s <SERIAL> getvar battery-soc-ok         # expect "battery-soc-ok: yes"
python3 <release>/tools/piano-switch.py --serial <SERIAL> --images <release>/boot --rollback android-set
# expect "Active A boot triplet written; remain in Fastboot for a RAM readback before reboot."
fastboot -s <SERIAL> reboot
```

- **GNOME Initial Setup** creates the first account. After [step 8a](#8a-recommended-install-your-units-files-before-the-first-boot)
  touch works; otherwise use the magnetic keyboard (touch is off until step 10). Skip the network
  page. Someone must be at the tablet: until the account exists and developer mode is on (step 8a or
  10) the host cannot reach it (developer mode needs an account and refuses root logins), and the only
  way back is Power + Volume Down.
- **Computer name.** The account page fills its *Computer* field with your user name and makes it
  the hostname, replacing the image's `xiaomipad-8pro` (7.2.6-piano7 build); edit the field for
  another name, or later run `sudo hostnamectl hostname --static <name>`. The pretty name
  "Xiaomi Pad 8 Pro", which Bluetooth shows, stays.
- **Clock.** The hardware clock cannot be written. With piano-ubuntu-desktop 0.1+20261010.6 or later
  (the 7.2.6-piano7 build) a boot starts from the time saved at the last shutdown or hourly
  (`fake-hwclock`), so the clock is behind by the time the tablet was off or in Android; earlier builds
  start every boot at systemd's built-in date, 2026-04-15. chrony corrects it once online, but only
  where Ubuntu's NTS servers can be reached: a router that answers every NTP request itself (as on the
  test network) gives no authenticated reply and the clock stays wrong. There, set it by hand,
  `sudo date -s 'YYYY-MM-DD HH:MM'`. A chrony file `/etc/chrony/conf.d/60-local.conf` with
  `authselectmode ignore` would accept the unauthenticated time instead; it gives up NTS
  authentication, and the image does not set it.
- The slot is marked as successfully booted after the boot completes:
  `sudo piano-slot-success --check` should report `"state": "already-successful"`.

Until step 10: no Bluetooth, a random Wi-Fi MAC address, no switching from Ubuntu, and kernel
updates leave slot A unchanged (the addresses are applied by the boot set rebuilt there). Touch works
from the first boot only after step 8a. Initial Setup's keyboard page rebuilds the initrd; without
`boot-profile.json` and `boot-signing.pem` in `/etc/piano` this leaves the boot set alone.

## 10. Install your unit's files

**Copy the files to the tablet** over USB with developer mode (SSH over the USB cable; USB host and
external drives are not supported). In a terminal on the tablet (Ctrl+Alt+T):

```bash
sudo piano-devmode on      # already on after step 8a
piano-devmode status       # expect "developer mode: enabled, active" and "SSH socket: active (192.168.88.2 port 22)"
```

On the host, with `<USER>` the account from Initial Setup:

```bash
python3 tools/piano-devmode-ssh.py --check     # expect "... 192.168.88.10 -> 192.168.88.2 ready"
```

If the host did not take the DHCP address, `--check` prints the `ip` command to set it.

**Create the partition map** unless step 8a made it. On the tablet:

```bash
d=$(lsblk -no PKNAME "$(readlink -f /dev/disk/by-partlabel/boot_a)"); readlink -f /sys/block/$d/device
# expect a path ending in ":4" (LUN 4)
sudo sfdisk --json /dev/$d > ~/boot-lun.json
```

On the host:

```bash
scp <USER>@192.168.88.2:boot-lun.json .
python3 tools/extract-boot-partitions.py --input boot-lun.json --profile boot-profile.json --output boot-partitions.json
# expect init_boot_a 8388608 B, vendor_boot_a and boot_a 100663296 B each
```

This route replaces the hand-written map of earlier versions of this guide and has not yet run on
the tablet.

**Copy the files:**

```bash
scp -r thp-calibration.json bluetooth-address wlan-address boot-partitions.json boot-profile.json \
  boot-signing.pem android-set piano-device-support_<version>_arm64.deb <USER>@192.168.88.2:
```

After step 8a four of the files are already in `/etc/piano`; copy only `boot-profile.json`,
`boot-signing.pem`, `android-set` and the package.

> **piano-device-support 0.1+20261010.6 or later is required for this step.** The v0.1.0-preview root
> ships 0.1+20261010.3, whose `piano-boot-switch` refuses every command on the release boot set with
> `"code": "serial-mismatch"`: the release command line carries no `androidboot.serialno`, the
> bootloader passes it only in `/proc/bootconfig`, and 0.1+20261010.3 read `/proc/cmdline` only
> (fixed in 0.1+20261010.5). From 0.1+20261010.6, kernel and initrd updates on a running persistent
> boot without `boot-partitions.json` leave the boot set and slot A unchanged instead of failing.
> Build the package ([BUILD.md](BUILD.md)), copy it with the files and install it first:
> `sudo dpkg -i piano-device-support_<version>_arm64.deb`. A root that already has 0.1+20261010.6 or
> later (`dpkg-query -W piano-device-support`; the 7.2.6-piano7 build has 0.1+20261010.7) needs
> neither the package nor the `dpkg -i` below.

**Install the files, store the Android set and rebuild the boot set:**

```bash
cd ~
sudo dpkg -i piano-device-support_<version>_arm64.deb
sudo install -m 600 bluetooth-address wlan-address thp-calibration.json boot-profile.json \
  boot-signing.pem boot-partitions.json /etc/piano/       # after step 8a: boot-profile.json boot-signing.pem
sudo piano-boot-switch status          # expect "occupant": "ubuntu" and "backup_gpt": "valid"
sudo piano-boot-switch import-android --from ~/android-set     # expect "result": "imported"
sudo piano-boot-update $(uname -r)
# expect "Piano boot image set prepared for <release>" and "Slot A now holds store/ubuntu"
sudo systemctl reboot
```

If Initial Setup ran with `boot-profile.json` and `boot-signing.pem` already in `/etc/piano` (step 8a
of earlier versions of this guide), `sudo dpkg --audit` reports `dracut` half-configured and `status`
reports `"occupant": "ubuntu.prev"`: slot A still holds the release set, now `ubuntu.prev`, and
`ubuntu/` holds a set that was not written. After installing the package and the files, run
`sudo piano-boot-switch to-ubuntu` (expect `"result": "written"`) before `piano-boot-update` or
`sudo dpkg --configure -a`, either of which would otherwise delete the set in slot A. Then continue
with the commands above and finish with `sudo dpkg --configure -a` (`sudo dpkg --audit` prints
nothing). The test unit was recovered this way on 2026-10-10.

The new set carries your addresses, serial and key; the release set is kept as `ubuntu.prev`. After
the reboot:

```bash
sudo piano-boot-switch verify          # expect exit status 0
```

Then delete the copies in your home directory (`rm -r ~/android-set ~/boot-signing.pem ...`) and,
in a terminal on the tablet, turn developer mode off; it was on for the installation only:

```bash
sudo piano-devmode off
piano-devmode status       # expect "developer mode: disabled, inactive"
```

`sudo piano-devmode on` turns it on again when you need the host connection. While on, it accepts
every local account with a password over the USB cable; see [device/devmode](../device/devmode/README.md)
to restrict it to SSH keys. From piano-device-support 0.1+20261010.7 its SSH socket accepts
connections on the USB network interface `usb0` only, not over Wi-Fi. If `ip -brief link` on the
tablet shows the USB link under another name, that socket does not start and the host cannot log in;
use the tablet's own terminal.

If the rebuilt set does not boot: Power + Volume Down, then write the release `boot/` set back from
the host ([FLASHING.md](FLASHING.md#from-the-host-piano-switchpy)).

## After installation

- **Switching and recovery:** [FLASHING.md](FLASHING.md).
- **Packages:** run `sudo apt update` before the first `apt install`. The image carries no indexes of
  its package sources (from the 7.2.6-piano7 build none at all), and apt then only reports "Unable
  to locate package", without suggesting `apt update`. The 7.2.6-piano7 build also removes Ubuntu's
  generic kernels and, with them, the C library headers: install `build-essential` before compiling
  software.
- **Kernel updates:** install the new `linux-image-<release>` package with `dpkg -i`; it rebuilds
  the boot set and rewrites slot A when it holds Ubuntu. Details: [AGENT-GUIDE.md](AGENT-GUIDE.md) §5.
  Roots from the 7.2.6-piano7 build swap to zram (`systemd-zram-generator`); a kernel without
  `CONFIG_ZRAM` (7.2.6-piano6 and earlier) booted on such a root, for example an older rollback set,
  waits about 90 s for `/dev/zram0` (measured in QEMU).
- **Android:** the first Android boot re-creates its data and takes several minutes. Reinstall the
  root manager app if you need root; the root-patched `init_boot_a` is unchanged. After changing the
  root patch in slot A, refresh the stored Android set ([FLASHING.md](FLASHING.md#image-sets)).
- **Known issues and support status:** [README](../README.md#support-matrix), the release's
  `RELEASE-NOTES.md`.

## Steps without a project tool in v0.1

| Step | State |
|---|---|
| Android root | the root manager's own procedure |
| Partition backup and manifest (step 2) | standard `adb`/`dd` commands |
| Wi-Fi address, boot profile (step 3) | standard commands; no generator |
| New partition table (step 5) | standard `sgdisk`/`sfdisk` on a loop device |
| Writing the partition table (step 6) | standard `dd` commands in the release's maintenance RAM image |
| Restoring the original partition table and removing Ubuntu | no tool and no verified procedure; keep the GPT backups |
