# piano-switch: switch to Ubuntu from Android

A KernelSU-Next module for stock Android on piano. Its action button writes the
Ubuntu boot set into the active A slot and reboots. The module holds scripts
only; the images come from the Ubuntu root filesystem.

Status: the host tests pass. The script has also run on the device, as the
shell user, against regular files. The module has not been installed, and it
has not written a real partition.

## What the action does

`action.sh` runs `piano-switch.sh` with `/system/bin/sh`. The script uses POSIX
sh and toybox, and does the following:

1. Requires root, `ro.product.device=piano`, and
   `androidboot.slot_suffix = "_a"` in `/proc/bootconfig`. It never chooses or
   changes a slot.
2. Takes the lock `/data/adb/piano-switch/lock`.
3. Resolves `init_boot_a`, `vendor_boot_a`, `boot_a` and `linux_rootfs` under
   `/dev/block/by-name`, and reads each partition's size.
4. Refuses if `linux_rootfs` is already mounted, is not ext4, or has
   `needs_recovery` set. It then mounts the filesystem `ro,noload` on
   `/data/adb/piano-switch/mnt`. Android never writes the Linux filesystem or
   the GPT.
5. Checks both sets under `/var/lib/piano/switch/{ubuntu,android}/`. Each set
   holds `init_boot.img`, `vendor_boot.img` and `boot.img` plus a
   `SHA256SUMS` file. Every image must match its single checksum line and be
   exactly the size of its partition.
6. Hashes the three slot partitions in full. They must equal the `android/`
   set:
   - If they equal the `ubuntu/` set, it writes nothing and does not reboot.
   - If they equal neither set, it refuses. The fix is to boot Ubuntu and run
     `piano-boot-switch import-android`, or to refresh `android/` otherwise.
7. Writes `init_boot`, then `vendor_boot`, then `boot` with
   `dd conv=notrunc,fsync`, and reads each partition back. It ignores
   HUP/INT/TERM while writing, and reads all three back once more at the end.
8. Unmounts, runs `sync`, and runs `svc power reboot`.

If any write or readback fails, the script writes the `android/` set back and
does not reboot.

Exit status:

| Status | Meaning |
|---|---|
| 0 | Switched, check passed, or nothing to do |
| 1 | Refused before any write |
| 2 | Write failed; the Android set is restored |
| 3 | Write failed and the restore failed too. Do not reboot; restore the Android set with fastboot |

`piano-switch.sh` takes two options:

- `--check` runs every step up to and including the occupant check, and writes
  nothing.
- `--no-reboot` writes and verifies, then leaves the reboot to the user.

The log goes to `/data/adb/piano-switch/switch.log`.

Writing with `dd` from Android leaves the slot attributes alone. ABL resets the
successful bit and the retry counter only on a Fastboot `flash boot*`.

## Prerequisites

- **Android root.** KernelSU-Next in LKM mode, with its init_boot patched from
  the stock OTA init_boot.
- **The `android/` set.** `/var/lib/piano/switch/android/` must equal what slot
  A holds while Android runs: stock boot, the KernelSU-patched init_boot and
  stock vendor_boot. If that set still carries an older init_boot (for example
  Magisk), the action refuses.
- **The `ubuntu/` set.** `/var/lib/piano/switch/ubuntu/` must hold the
  installed Ubuntu set, in the same format that `piano-boot-switch` reads.
- **A clean Ubuntu shutdown.** Ubuntu must shut down cleanly before you go to
  Android, so that the ext4 journal does not need recovery.

## Build, install and test

```
./build.sh OUTDIR                      # OUTDIR/piano-switch-ksu-<version>.zip and .sha256
tests/run-tests.sh                     # host shell (dash)
tests/run-tests.sh mksh                # Android's shell
tests/run-tests.sh mksh TOYBOX_APPLETS # mksh with toybox applet links ahead of PATH
```

The tests need `mkfs.ext4` and `debugfs`. Partitions are regular files, and
`linux_rootfs` is a real ext4 image built with `mkfs.ext4 -d`. Shims replace
`mount`, `umount`, `blockdev`, `svc` and `getprop`. The `dd` shim injects write
failures and corrupt readbacks. The tests cover:

- check mode
- a full switch and `--no-reboot`
- a slot that already holds Ubuntu
- every refusal path
- a restore after a failed write, and a failed restore

`PIANO_SWITCH_TEST=1` exists for these tests only. It accepts regular files in
place of block devices and skips the root check.

Install with root (KernelSU activates modules at the next boot):

```
adb push piano-switch-ksu-<version>.zip /data/local/tmp/
adb shell su -c '/data/adb/ksud module install /data/local/tmp/piano-switch-ksu-<version>.zip'
adb reboot
```

You can also install from the Modules page of the KernelSU Next manager.

## Device verification (not yet done)

1. `adb shell su -c 'ksud module list'` lists `piano-switch`, and the manager
   shows its action button.
2. `adb shell su -c 'sh /data/adb/modules/piano-switch/piano-switch.sh --check'`
   prints `CHECK OK`. Check the following:
   - The ro,noload mount works from the KernelSU domain.
   - The files on `linux_rootfs` can be read even though they have no SELinux
     label.
   - `/proc/bootconfig` can be read.
3. While the store's `android/` set is stale, `--check` must refuse with the
   import-android hint.
4. Press the action button, or run
   `su -c 'ksud module action piano-switch'`. Then confirm all of the
   following:
   - The log shows all three readbacks.
   - The device reboots into Ubuntu.
   - Fastboot `slot-successful:a` and `slot-retry-count:a` are unchanged.
