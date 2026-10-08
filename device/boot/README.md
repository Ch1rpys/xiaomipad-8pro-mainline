# Persistent boot integration

The persistent desktop kernel variant enables the reviewed UFS path and ext4.
`build-kernel-deb.py --boot-dtb` carries its audited ABL DTB with the matching
kernel and modules. The device package adds the platform initrd entry, input
service, local firmware, and distro kernel/initrd hooks.

`tools/build-persistent-boot.py` constructs v4 boot/init_boot/vendor_boot images
from the installed distro initrd, the device's original header geometry and
rollback indices, its root PARTUUID, local Bluetooth address and signing key.
It writes regular files only. Normal images have no development console or
expiry timer; both require explicit debug options. A v2 image is also emitted
for bounded testing against the persistent root before changing the boot slot.

`tools/piano-switch.py` is the host Fastboot writer for installation and
recovery; it leaves Fastboot running for a separate RAM readback.

The local filesystem installation and v4 boot from the active A slot work
on the test unit. Boot version/SPL and AVB properties must come from the local
stock image; an unlocked loader still needs a well-formed boot contract.
With the full module set, sync_state releases the boot-time power, clock and
interconnect state. The display therefore depends on the kernel DTS declaring
the firmware scanout's power domains, clocks and bandwidth on the
simple-framebuffer node, and the GPU on its MX and GMXC power-domain votes.
The installer is not published. Existing RAM diagnostics remain RAM-only
images.

The empty `init_boot` ramdisk is written as fixed bytes, so a set built on
the host (Python 3.12) and one rebuilt by `piano-boot-update` on the device
(Python 3.14) share `boot.img` and `init_boot.img` for the same inputs.
`vendor_boot.img` differs whenever the dracut initrd differs.

## Slot A switching from Linux

The tools below are packaged in `piano-device-support` and tested offline
with synthetic disks and images. They have not yet run on the device.

### Image store

`/var/lib/piano/switch/` holds three image sets; nothing else in it is an
image set:

| Directory | Content |
|---|---|
| `ubuntu/` | current Ubuntu set, written by `piano-boot-update` or `import-ubuntu` |
| `ubuntu.prev/` | the Ubuntu set before it |
| `android/` | the Android set: stock `boot`, the root-patched `init_boot`, stock `vendor_boot` |

Each set has `boot.img`, `init_boot.img` and `vendor_boot.img`, each exactly
the size of its partition, and a `SHA256SUMS` file with one
`<sha256>  <name>` line per image. The store also holds `.lock`,
`state.json` (last write, the slot occupant and its hashes) and `switch.log`.
`piano-boot-switch status` lists any other entry as stray; no tool reads
it. The Android-side KernelSU module (`device/android/piano-switch-ksu/`)
reads the same layout. Slot A's occupant is the set whose `SHA256SUMS`
equals the SHA-256 of the three partitions' content; GPT attribute changes
do not affect it.

### `piano-boot-switch`

```
piano-boot-switch status                    # attributes, occupant, per-set hashes and matches
piano-boot-switch verify                    # every set and the occupant; never writes
piano-boot-switch to-android [--dry-run] [--reboot] [--desktop]
piano-boot-switch to-ubuntu  [--dry-run] [--reboot] [--desktop] [--only-if-ubuntu]
piano-boot-switch import-android [--from DIR] [--dry-run]
piano-boot-switch import-ubuntu  [--from DIR] [--dry-run]
```

- It runs only on the restored piano identity with the installed device
  profile serial and partition map, finds the boot LUN by its GPT entries
  below `1d84000.ufshc`, and accepts only slot A: A active with priority 3
  and not unbootable, B inactive, and any slot suffix in bootconfig or the
  command line `_a`. It never selects a slot and never writes the GPT,
  `vbmeta`, slot B or other partitions.
- `to-*` writes only when slot A holds a known store set, which then serves
  as the rollback. Both sets are checked against `SHA256SUMS` and the
  partition sizes first; Ubuntu sets must carry `piano.boot=persistent` in
  the boot command line and Android sets must not. `init_boot_a`,
  `vendor_boot_a` and `boot_a` are written in that order with HUP, INT,
  TERM and QUIT blocked, and each is read back in full from the device. A
  failure writes the previous set back and exits non-zero without a reboot.
  The three writes are not atomic.
- `import-android` replaces `android/` with the current slot content, for
  example from a RAM-booted Linux while Android is in the slot, or with a
  directory holding the three images and `SHA256SUMS`. Content carrying the
  Ubuntu marker is refused.
- `import-ubuntu` registers the running set, or a directory, as `ubuntu/`
  and moves the old set to `ubuntu.prev/`. From the slot it requires that
  this boot used the slot's command line. It is needed once after a host
  Fastboot install of a set that is not in the store.
- Writes are logged to the journal (`journalctl -t piano-boot-switch`),
  `switch.log` and `state.json`.

The app grid entry **Switch to Android** (切换到 Android) runs
`pkexec /usr/sbin/piano-boot-switch to-android --desktop`. Its polkit action
`io.github.piano.switch.to-android` matches exactly that program and first
argument and asks for administrator authentication (`auth_admin_keep`).
With `--desktop` the tablet reboots once slot A reads back as the Android
set; a failure is sent to the caller's notification service and nothing
reboots. GNOME's own restart-into-another-system needs the UEFI Boot Loader
Interface, which ABL does not provide.

### Kernel and initrd updates

`piano-boot-update` (from the kernel `postinst.d` and initramfs
`post-update.d` hooks) builds a new set into `ubuntu/` and moves the old one
to `ubuntu.prev/`. On a running persistent piano boot it then runs
`piano-boot-switch to-ubuntu --only-if-ubuntu`: if slot A holds an Ubuntu
store set it is rewritten in place, so the booted kernel and initrd match
the installed modules; Android in the slot stays. Every kernel or initrd
update therefore writes a set to slot A that has not booted yet. Images
built in a chroot, QEMU or a RAM root only update the store.

### Marking slot A successful

ABL decrements an unsuccessful slot's retry count on every boot, and
`fastboot flash boot_a` resets it to 7 and clears the successful bit; at 0
the slot becomes unbootable. The Android HAL marks the slot after each
Android boot, and switching with `dd` from either system leaves the bits
alone, so the problem arises after a host Fastboot install.

`piano-slot-success.service` runs `piano-slot-success --mark` after
`boot-complete.target` on persistent boots (`piano.boot=persistent`). The
tool sets bit 54 (successful) of the `boot_a` entry and nothing else. It
refuses unless both GPT copies pass the signature, revision, header-size,
LBA cross-link, entry-location and CRC checks and their entry arrays are
identical; slot A passes the judgement above; the retry count is not 0;
this boot used the slot's command line (a `fastboot boot` debug image
carries `piano.debug=1`, which the slot image lacks, and is refused); and the
slot holds `ubuntu/` or `ubuntu.prev/`. It writes the backup copy first, then the primary, reads both
back and compares them byte for byte with the expected single-bit change.
Before and after copies go to `/var/lib/piano/slot/`. `--check` and
`--dry-run` never write; all modes print JSON.

### Internal storage in GNOME

`90-piano-internal-storage.rules` sets `UDISKS_IGNORE=1` on every UFS
partition whose GPT type is not the Linux filesystem GUID, so Files and the
Shell no longer offer Android, firmware, `persist` or modem volumes. GNOME's
About page still reports the whole UFS, because it adds up disks, not
partitions.

## Suspend is disabled in the first release

Suspend and resume have not been validated on piano. The kernel offers
`s2idle` and `deep`, but neither wake path has been exercised, and a stuck
resume can only be cleared with a forced reboot. `piano-device-support`
therefore ships one policy in two standard places:

- `/usr/lib/systemd/sleep.conf.d/50-piano-first-release.conf` sets
  `AllowSuspend`, `AllowHibernation`, `AllowHybridSleep` and
  `AllowSuspendThenHibernate` to `no`, so logind refuses every sleep request
  from any desktop, key handler or command line.
- `/usr/share/glib-2.0/schemas/50_piano-first-release.gschema.override` sets
  the GNOME idle actions (`sleep-inactive-ac-type`,
  `sleep-inactive-battery-type`) to `'nothing'`, so the session does not
  request suspend. A GSettings vendor override is used because the GDM and
  gnome-initial-setup dconf profiles have no system database; the distro
  `glib-compile-schemas` trigger compiles it.

Lock screen and power-button settings are unchanged. Ubuntu's power-button
action is the interactive end-session dialog; a `suspend` action would fall
back to that dialog because logind reports suspend as unavailable. UPower's
critical-battery action falls back from hybrid sleep and hibernation to
power-off. An administrator can re-enable sleep for testing with a same-named
file in `/etc/systemd/sleep.conf.d/`. Both files are removed once s2idle and
deep suspend/resume are validated on piano.
