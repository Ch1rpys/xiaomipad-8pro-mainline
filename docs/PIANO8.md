# Merged piano8 candidate

This candidate combines native P81 display, the cleaned display-PM/clock series,
WN8030 keyboard and charging3. `kernel/source.json` and `kernel/abi.json` bind the
exact build. The merged image has **not** been tested on the tablet. Component
results do not establish combined hardware support; charging3 is still an
offline candidate. Camera and temporary DIAG commits are excluded.

The charging-only branch previously produced an unmerged `7.2.6-8.1` prototype.
The requested consolidated ABI remains `7.2.6-piano8`; its package upload is
`7.2.6-8.2` to distinguish the final candidate. Retain that old artifact only as
historical evidence. Use the merged manifest and hashes, never its modules or
`879164d18e78…` kernel deb. The installed rollback release is piano7.

## One RAM check, before installation

The assistant will run this sequence later. Offline assembly runs no device
commands. Reserve the target, verify its serial, Android build/slot/root,
complete saved backup, fresh battery at least 40%, known slot-A Android set,
and recovery route using the existing runner. An unknown or low battery stops
the test. Keep all ADB/Fastboot calls bound to `PIANO_SERIAL`.

Verify the delivery's SHA256SUMS and the **embedded** RAM DTB against the ABI-3
booted reference. Its root must contain `qcom,msm-id = <0x100027f 0x20000>` and
`qcom,board-id = <0 0>`. The local README gives the exact hash and checker.
The RAM image must be strictly smaller than 93,000,000 bytes.

Use the bounded runner from Android. Its single boot command is:

```sh
fastboot -s "$PIANO_SERIAL" boot "$BUNDLE/ram/boot-ram-check.img"
```

The image carries the complete matching modules in a read-only RAM bind and
uses the installed Ubuntu root and its existing, previously tested GDM
autologin. It creates no account or permanent login policy. The assistant must
confirm an active **user Wayland session**, not merely GDM active. If the root's
autologin configuration has changed, restore the agreed test setup before this
run. Normal root logging still writes the installed filesystem.

At root startup save the full boot log, then check:

```sh
test "$(uname -r)" = 7.2.6-piano8
journalctl -k -b -o short-monotonic --no-pager > /run/piano8-kernel.log
# Expected: no matches; grep exit 1 means none, exit 2 is a read error.
grep -nE 'WARNING:|already (disabled|unprepared)|DSI.*lock failed|rcg didn.t update|dsi_err_worker' /run/piano8-kernel.log
cat /sys/class/drm/card*-DSI-1/status /sys/class/drm/card*-DSI-1/enabled
grep -E 'mode:.*3200x2136.*144' /sys/kernel/debug/dri/*/state
grep -iE 'Nanosic|WN8030' /proc/bus/input/devices
test -d /sys/module/hid_nanosic_wn8030
test -d /sys/module/xiaomi_mca
test -d /sys/class/power_supply/xiaomi-mca-usb
loginctl list-sessions --no-legend
```

Expect DSI-1 connected/enabled, **3200×2136 at 144 Hz**, keyboard/consumer/switch
interfaces and no touchpad on this accessory. Preserve current clock ownership,
INTF1/2 frame deltas, FIFO/underrun status and the kernel journal. The updated
native capture queries the actual CRTC; registration alone is not physical-key
or visual acceptance. No `PIANO_PLLDIAG` line is expected in this cleaned kernel.
Use the bounded display-PM script in the local bundle for one optional 10-second
OFF/ON cycle, retaining its existing power/error/session guards.

The existing helper requests Fastboot at kernel uptime 600 seconds. The runner
then returns the unchanged Android slot and records fresh identity/battery.
Require observed recovery; never infer it from elapsed time or repeat a failed
boot blindly. Do not install packages while `/usr/lib/modules` is the RAM bind.

## Install from the normal installed root

After RAM recovery, enter the existing piano7 Ubuntu through the established
switching path in [FLASHING.md](FLASHING.md). Keep developer mode enabled and a
verified host copy of both the Android and piano7 image sets. On piano7:

```sh
test "$(uname -r)" = 7.2.6-piano7
sudo piano-boot-switch verify
sudo test ! -e /var/lib/piano/piano8-rollback
sudo cp -a /var/lib/piano/switch/ubuntu /var/lib/piano/piano8-rollback
sudo apt-get install /var/tmp/piano8/debs/*.deb
sudo dpkg --audit
sudo piano-boot-update 7.2.6-piano8
sudo piano-boot-switch verify
sudo piano-boot-switch to-ubuntu --dry-run
```

Install the merged kernel, support, MiPPS-auth and desktop packages together.
The support update is required: ordinary `piano-boot-update` now derives the
KMS/GPU command line from the selected DTB, and dracut includes the early A830
firmware. The desktop package supplies DSI-1 200%/144 Hz system defaults; an
existing per-user monitors.xml may override them.

Kernel postinst may already rebuild the set and update the Ubuntu-owned slot.
An explicit update can rotate `ubuntu.prev` again, so the separately saved
`piano8-rollback` and installed piano7 package must remain intact. Verify the
new manifest's release, DTB/hash, `msm.separate_gpu_kms=0`, absence of debug flags,
slot occupant and rollback readability before powering down for a cold start.
Do not copy the RAM-debug triplet into the persistent store. No repartition or
B-slot operation is part of this update.

## Cold boot acceptance and rollback

Use monotonic timestamps from this boot and the standard acceptance capture:

| Measurement | Required budget |
|---|---:|
| simpledrm initialised | < 1 second |
| switch_root / root systemd userspace timestamp | ≤ 10 seconds |
| GDM active | ≤ 20 seconds |
| first GMU firmware load | ≤ 20 seconds |
| GMU/DRM errors over about 200 seconds | zero |
| 256 MiB cached RAM copy | ≥ 2 GB/s |

Also require HF AXI held from the first initrd observation, native DSI-1 at
144 Hz (both INTF counters within 5%), no clock/FIFO/underrun warnings, matching
module release, an actual desktop user session, and the keyboard/MCA checks
above. Full-module diagnostic XZ timings are recorded separately from the
installed-root dracut cold boot; the live-08 RAM budgets were not PASS.

If acceptance fails, preserve evidence and use the existing set switcher:

```sh
sudo piano-boot-switch import-ubuntu --from /var/lib/piano/piano8-rollback
sudo piano-boot-switch to-ubuntu --reboot --force
```

If Ubuntu is unreachable, use the host recovery command in FLASHING.md with
that verified piano7 copy. Confirm the old release and slot state after return.
The separate attended wall-charger test and its bounded rollback are described
in [CHARGING-TEST.md](CHARGING-TEST.md). MCA presence, policy enabled or successful
authentication does not prove net charging, thermal safety or 67 W.
