# Attended 5 V charging experiment

This candidate is untested on the tablet. The automatic udev policy has not
passed its cold-boot gate; do not deploy its candidate support deb. The manual
one-boot experiment below does not install that policy. It uses the existing Xiaomi MCA
transport and adds no PD/PPS negotiation, MiPPS, SC8541 control or temperature
policy. ADSP still controls JEITA, float voltage and charging enable.

`input_current_limit` and `constant_charge_current` are the only writable
power_supply properties. Values are in microamps; the MCA payload is an integer
in milliamps. The minimum is 100 mA. Values over the following caps are rejected;
sub-mA values inside the range round down. Unknown/unsupported raw charger types
are refused, including automatic ICL restoration when the type is unknown.

| Firmware type | Standard USB type | ICL cap (mA) | FCC cap (mA) |
|---|---|---:|---:|
| SDP (1) | SDP | 500 | 500 |
| CDP (2) | CDP | 900 | 900 |
| DCP, QC2/3/3_B/3P5 (3, 5–8) | DCP | 1500 | 2000 |
| Type-C (9) | C | 1500 | 2000 |
| PD/verified PD (10–11) | PD | 1500 | 2000 |
| PPS detected (12), no PPS requests | PD_PPS | 1500 | 2000 |
| FLOAT/OCP (4, 15) | Unknown | 1000 | 1000 |
| Unknown, reserved, ACA, unlisted | Unknown | writes refused | writes refused |

The caps come from this unit's stock `mca,strategy_buckchg` configuration.
The vendor `strategy_buckchg_select_charg_para()` maps QC to DCP at 5 V before
selecting the table: `in_hvdcp=1200` is the higher-voltage QC2 branch, not its
5 V limit. FCC is limited to the stock 5 V DCP value, 2000 mA.
Protocol reference: [vendor MCA, commit 8276ba954d80](https://github.com/unmoved21/android_kernel_xiaomi_onyx/tree/8276ba954d8076303a5ae0f7b15d4092d66bdff6/drivers/power/supply/mca)
(GPL-2.0; unmoved21's source import). [blu-sharky piano_mca.c, 453bb567f2fc](https://github.com/blu-sharky/linux-piano/blob/453bb567f2fc/drivers/power/supply/piano_mca.c)
(GPL-2.0-only, bluseliu50) was cross-checked; its charging policy was not imported.

The device-support candidate contains one `80-piano-charging.rules` file. It
sets ICL on add/change for SDP, CDP, DCP, C, PD and PD_PPS, skips unknown/offline
supplies and avoids rewriting an already equal limit. It does not set FCC.
The kernel rechecks the firmware type before accepting the write. Reading the
supply alone never enables this userspace policy. `usb_type` now describes the
known non-SDP types; the existing GLINK read requests and values keep their
wire format. The read-only `usb_type` text therefore has a larger available list.

## One boot on the installed Ubuntu system

Use the supplied `one-boot/SHA256SUMS` and `manifest.json`. The temporary
`xiaomi_mca.ko` is for **7.2.6-piano7 only**, with the exact piano7 config and no
changes outside this driver. Do not install it in `/lib/modules`, rebuild an
initrd, write a boot partition or mix it with another kernel release. A full
kernel build is provided for offline inspection; it is not a newly allocated
installable kernel ABI. The support deb is a separate policy candidate: **do
not install it for the baseline experiment**. The accompanying verification report records the rule's cold-boot status;
syntax checks or late rule execution alone do not qualify it. Installation on
piano remains unverified.

Reserve the tablet for this experiment; no other device test may run concurrently.
The user must be present, with a wall charger able to supply at least 5 V/1.5 A.
Use 40–90% battery and room temperature. The two battery currents must be read
from `bq27z561-*`, where positive means charging, not the USB input current.

1. Start installed Ubuntu with developer mode enabled. Connect from the host
   using the existing helper and the unit's serial, then copy the bundle:

   ```sh
   # Host: set PIANO_SERIAL and PIANO_USER to this tablet and its existing account.
   tar -C /path/to/one-boot -cf - . | \
     python3 tools/piano-devmode-ssh.py --serial "$PIANO_SERIAL" "$PIANO_USER" \
       'mkdir -p /tmp/piano-charging-test && tar -xf - -C /tmp/piano-charging-test'
   python3 tools/piano-devmode-ssh.py --serial "$PIANO_SERIAL" -t "$PIANO_USER"
   ```

2. In that device shell, set `PIANO_SERIAL` to the same unit and run the following
   as one block. The identity check must succeed before unloading anything:

   ```sh
   sudo bash -s -- "$PIANO_SERIAL" <<'SH'
   set -eu
   serial=$1
   cd /tmp/piano-charging-test
   sha256sum -c SHA256SUMS
   python3 - "$serial" <<'PY'
   import sys
   sys.path.insert(0, '/usr/lib/piano/boot')
   from piano_bootslot import Host, require_piano, firmware_serial
   h = Host()
   require_piano(h)
   assert firmware_serial(h) == sys.argv[1], 'wrong or missing firmware serial'
   PY
   test "$(uname -r)" = 7.2.6-piano7
   cmp /boot/config-7.2.6-piano7 config
   sha256sum -c installed-kernel.sha256
   mkdir -p /run/udev/rules.d
   ln -s /dev/null /run/udev/rules.d/80-piano-charging.rules
   udevadm control --reload
   udevadm settle
   rmmod xiaomi_mca
   insmod ./xiaomi_mca.ko
   mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug
   systemd-run --unit=piano-charging-test --collect \
     --property=RuntimeMaxSec=10min \
     --property='ExecStopPost=/usr/bin/systemctl reboot' \
     /usr/bin/python3 /tmp/piano-charging-test/charging-test-device.py \
     --serial "$serial" --attended-wall-charger \
     --output /var/log/piano-charging-01
   SH
   ```

   Use a new output directory if one already exists. The transient service's
   stop action reboots even if the collector exits early or exceeds its time
   budget. Nothing from this experiment is enabled for the next boot.

3. Move the cable to the **wall charger**, within 120 seconds. The USB SSH link
   disappears; the local transient service continues. It records the charger
   type, VBUS/IBUS, both gauges' current, capacity, voltage and temperature every
   10 seconds for a 120-second baseline. It then writes ICL=1500000, checks the
   readback, writes FCC=2000000, checks again and records 300 seconds. It saves
   raw samples, phase-boundary MCA status/stats/frames and dmesg, then reboots.
   A baseline that already charges is valid evidence; do not manufacture a
   discharge baseline or attribute an existing charge rate to this change.

4. After the reboot, reconnect the host cable and use the same serial-bound
   developer-mode helper to retrieve `/var/log/piano-charging-01/`. Read MCA
   status again to check the firmware's restored defaults. The installed
   original driver is loaded and the `/run` rule mask has disappeared.

**PASS:** both gauges' median current in the last minute is positive and the
mean capacity percentage at the end is above the pre-write value. Inspect all
samples, MCA error counters and dmesg as well: no transport timeout, firmware
error or reset is acceptable. A positive current with unchanged integer percent
in five minutes does not meet this PASS criterion; retain the trace and report
the result as unproven, not proof that charging is impossible.

**Abort/fail:** source absent/unknown/changed, VBUS outside the 4.5–5.5 V test
window, either gauge outside 15–45 °C, missing gauge/identity/config, write or
readback failure, MCA error, or the above PASS criterion not met. The voltage and
temperature windows are experiment stop conditions, not new charging settings
or a thermal control loop. If the user observes unusual heat or instability,
unplug the charger and use the normal reboot/recovery path.

**Revert:** reboot restores the installed driver and is expected to reset ADSP
current requests; verify the defaults by reading them. Do not rely on module
unload to restore FCC. If the policy deb was installed separately, restore the
previous support deb (or mask its rule persistently), reload udev, then reboot;
otherwise it will apply ICL again on the next coldplug. No kernel deb, initrd,
boot set or firmware is installed by the one-boot procedure above.

Not established offline: actual wall-source detection, write acceptance and
readback on this firmware, effective ICL/FCC, charging gain, long-term thermal
behaviour, PD source capability, plug transitions and reset defaults. ADSP's
JEITA/float policy is not a copy of every Android MCA temperature vote: for
example the stock HLOS low-temperature FCC curve is stricter. The test does not
qualify unattended or all-temperature charging.
