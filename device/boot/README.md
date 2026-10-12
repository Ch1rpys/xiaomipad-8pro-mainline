# Persistent boot integration

The persistent desktop kernel variant enables the reviewed UFS path and ext4.
`build-kernel-deb.py --boot-dtb` carries its audited ABL DTB with the matching
kernel and modules. The device package adds the platform initrd entry, input
service, local firmware, and distro kernel/initrd hooks.

`tools/build-persistent-boot.py` constructs v4 boot/init_boot/vendor_boot images
from the installed distro initrd, the device's original header geometry and
rollback indices, its root PARTUUID (or the GPT name `linux_rootfs`), the optional
local Bluetooth and Wi-Fi addresses and a signing key.  A release root ships a set
built with `--root-partlabel linux_rootfs --no-serial` and no addresses; until the
owner installs `boot-profile.json` and `boot-signing.pem` in `/etc/piano`, and on a
running persistent boot also `boot-partitions.json`, `piano-boot-update` keeps that
set and slot A unchanged and succeeds (docs/RELEASE.md).
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
piano-boot-switch to-android [--dry-run] [--reboot] [--desktop] [--force]
piano-boot-switch to-ubuntu  [--dry-run] [--reboot] [--desktop] [--force] [--only-if-ubuntu]
piano-boot-switch import-android [--from DIR] [--dry-run]
piano-boot-switch import-ubuntu  [--from DIR] [--dry-run]
```

- It runs only on the restored piano identity with the installed device
  profile serial and partition map, finds the boot LUN by its GPT entries
  below the internal UFS host, and accepts only slot A: A active with priority 3
  and not unbootable, B inactive, and any slot suffix in bootconfig or the
  command line `_a`. The UFS host is the one platform device whose devicetree
  node is compatible with `qcom,sm8750-ufshc` and which `ufshcd-qcom` has
  bound; it is never found by name. Mainline calls it `1d84000.ufs`
  (`/sys/devices/platform/soc@0/1d84000.ufs`); `1d84000.ufshc` is only ABL's
  `androidboot.bootdevice` name. It never selects a slot and never writes the GPT,
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
- Before requesting a reboot, the current `piano-device-support` tool lists
  logind's `shutdown` inhibitors in `block` mode with their who/why.
  `handle-*` and delay inhibitors are not shutdown blocks. `systemctl` stderr
  is printed verbatim, including on success. If reboot fails, the tool exits 1
  and explicitly names the set still in slot A and the next boot's OS; the
  JSON `written`/`unchanged` result describes the slot operation only.
  Save your work and reboot normally, or run
  `sudo piano-boot-switch to-android --reboot --force` to ignore inhibitors
  (`systemctl reboot -i`). Retrying when Android already occupies slot A does
  not rewrite it. `--force` requires `--reboot` or `--desktop`; it does not
  bypass any write checks. `--dry-run` never reboots.

The app grid entry **Switch to Android** (切换到 Android) runs
`pkexec /usr/sbin/piano-boot-switch to-android --desktop --force`. Its polkit action
`io.github.piano.switch.to-android` matches exactly that program and first
argument and asks for administrator authentication (`auth_admin_keep`).
This entry uses `--force`, not a GNOME logout dialog: save your work first;
unsaved changes may be lost. Both the entry's comment and the polkit prompt
state this policy (authentication may be cached). Using `--desktop` alone
respects inhibitors, as the SSH command does.
With `--desktop` a reboot is requested once slot A holds the Android set;
a failure is sent to the caller's notification service, including systemctl's
error and the next boot's OS. GNOME's own restart-into-another-system needs
the UEFI Boot Loader Interface, which ABL does not provide. The updated
inhibitor and desktop behavior has unit-test coverage; device testing is pending.

### Kernel and initrd updates

`piano-boot-update` (from the kernel `postinst.d` and initramfs
`post-update.d` hooks) builds a new set into `ubuntu/` and moves the old one
to `ubuntu.prev/`. On a running persistent piano boot it then runs
`piano-boot-switch to-ubuntu --only-if-ubuntu`: if slot A holds an Ubuntu
store set it is rewritten in place, so the booted kernel and initrd match
the installed modules; Android in the slot stays. Every kernel or initrd
update therefore writes a set to slot A that has not booted yet. Images
built in a chroot, QEMU or a RAM root only update the store.

Only unique releases `<version>-piano<ABI>` (see `kernel/abi.json`) take
part, and, as flash-kernel does, only the newest installed one. An initramfs
update for an older kernel, or for the legacy `7.2.6-piano+` that
`linux-version` sorts above every `-piano<N>`, leaves the store and the slot
alone. On a running persistent boot without `/etc/piano/boot-partitions.json`
the update also leaves both alone and exits 0: the new set could not be
written, and a set rotated in without being written would leave slot A on
`ubuntu.prev`, which the next rotation deletes. `tools/extract-boot-partitions.py`
makes the map on the host from `sfdisk --json` of the boot LUN. After a piano kernel package is removed, the `postrm.d` hook runs
`piano-boot-update --removed <release>`: if that kernel owned `ubuntu/`, the
set is rebuilt for the newest remaining piano kernel (and slot A rewritten as
above), and a `ubuntu.prev/` that boots the removed kernel is deleted because
its modules are gone. A set's release is the `kernel_release` of its
`manifest.json`, or the Image banner in `boot.img` for older sets.

Each set's DTB carries two per-unit addresses that never enter the
repository. `/etc/piano/bluetooth-address` (required) becomes the WCN7860
Bluetooth `local-bd-address`; `/etc/piano/wlan-address` (optional, root,
mode 0600, one unicast `XX:XX:XX:XX:XX:XX` line, from `wlan/wlan_mac.bin` on
the stock `persist` partition) becomes the `local-mac-address` of
`/soc@0/pcie@1c00000/pcie@0/wifi@0`, which ath12k uses because this card
reports an all-zero address. `piano-boot-update` passes them to
`build-persistent-boot.py --bt-address-file` / `--wlan-address-file`; without
`wlan-address` the set has no Wi-Fi address and `wlp1s0` cannot be brought
up. A changed address takes effect with the next `piano-boot-update` run.

### Accepting a boot or kernel update

A boot can pass a one-time reading and still be degraded. With the display
clock controller built as a module, `clk_disable_unused` switched
`GCC_DISP_HF_AXI_CLK` off at about 2.6 s; in most boots non-display memory
traffic then stayed throttled (a 256 MiB copy at 36–47 MB/s instead of over
5 GB/s, GMU initialisation timing out), with the same software as a normal
boot. `tools/piano_boot_acceptance.py` keeps the acceptance criteria and their
budgets as data and evaluates them from saved captures. Replace `<release>`
with the kernel release being checked:

```sh
python3 tools/piano_boot_acceptance.py criteria           # criteria, budgets, profiles
python3 tools/piano_boot_acceptance.py evaluate --dir EVIDENCE --release <release> --json verdict.json
python3 tools/piano_boot_acceptance.py live --user USER --sudo --profile cold --release <release> \
  --save EVIDENCE [--scanout-probe piano-scanout-probe.py]
python3 tools/piano_boot_acceptance.py script [--initrd]  # the device-side read scripts
```

- Budgets: simpledrm initialised in under 1 s; `gcc_disp_hf_axi_clk` held by
  the framebuffer (clk_summary and CBCR) from the first initrd console and in
  the root; switch-root ≤ 10 s; gdm active ≤ 20 s; first GMU firmware load
  ≤ 20 s and no GMU timeout, OOB, hangcheck or GPU error line to at least
  180 s; every 256 MiB RAM copy ≥ 2000 MB/s; both DPU interfaces at 120 Hz
  with unchanged interrupt status and the GDM greeter in the scanout samples;
  a touch first frame without SPI/GPI errors; `hci0` up; no failed units;
  rpmhpd and every interconnect provider synced; the expected release running
  the root with only its own modules; `CONFIG_SM_DISPCC_8750=y`; and a FAST
  classification (not switch-root > 18 s, simpledrm to fb0 > 0.5 s or gdm
  inactive at 40 s).
- Each criterion is PASS, FAIL or UNAVAILABLE with the measured value; a
  missing or unparsable input is UNAVAILABLE, never FAIL. The verdict over a
  profile is PASS, FAIL or INCOMPLETE (exit 0, 1 or 3). `debug` is a debug RAM
  validation boot of the installed root: the criteria above and the slot
  attributes read in Fastboot before and after. `cold` is a release cold boot
  read over developer-mode SSH: no initrd console or Fastboot reading, plus
  the store manifest release and the slot occupant.
- An evidence directory holds `initrd-*.txt` (first initrd console),
  `root-*.txt` (root transcripts; name order is time order), `kmsg*.txt` (host
  `/dev/kmsg` capture), `journal*.txt` (`journalctl -b -o short-monotonic`)
  and `getvar-before.txt` / `getvar-after.txt`. Transcripts of the earlier
  measurement scripts are read as well.
- Kernel times come from `/dev/kmsg` or `dmesg`. Journal times of kernel
  messages before switch-root are journald receive times (simpledrm at 0.20 s
  was logged at 4.25 s) and are not used, so a read without root leaves
  `simpledrm_init` and the classification UNAVAILABLE.
- `live` checks the link with `piano-devmode-ssh.py --check`, runs the read
  script once through it and saves the transcript and `verdict-*.json`. With
  `--sudo` the password typed here is the first input line of `sudo -S`; a
  wrong password ends the read. The scanout criterion needs root and the DPU
  scanout probe, which is maintained outside this repository.
- The scripts only read (`/proc`, sysfs, debugfs, the kernel log,
  `piano-boot-switch status`, `GCC_DISP_HF_AXI_CBCR` through busybox
  `devmem`) and copy a 256 MiB buffer in RAM; the initrd script mounts debugfs
  if it is absent.
- `tools/test-piano-boot-acceptance.py` replays two scrubbed captures in
  `tools/fixtures/boot-acceptance/`: a validation boot (PASS) and a slow boot
  with dispcc as a module (FAIL on the classification, simpledrm, the initrd
  clock hold,
  switch-root, gdm, GMU, GPU errors, the copy, scanout, touch errors and the
  dispcc configuration).

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

`90-piano-internal-storage.rules` sets `UDISKS_IGNORE=1` on every partition
below the platform device bound to `ufshcd-qcom` (the internal UFS; USB disks
never match) whose GPT type is not the Linux filesystem GUID, so Files and the
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
