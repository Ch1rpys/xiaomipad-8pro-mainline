# One-boot charging candidate (piano8)

This is an offline candidate. No device result is claimed. Use the exact debs
and SHA256SUMS from the merged piano8 bundle. The earlier charging-only
`d03669c9a273` / `879164d18e78` package is superseded; do not install it as
the merged candidate. See [piano8 integration](PIANO8.md). Keep the installed piano7 kernel and
its verified boot set. Do not mix piano7 modules with the piano8 Image.

The candidate ports the community charging group into `xiaomi_mca`, preserving
`xiaomi-mca-usb`, standard microamp/microvolt properties, checked replies and
unknown-source refusal. All kernel policy switches default off. The support
package's udev-triggered `piano-charging.service` enables them after probe;
`pan_ack` is on the existing AltMode module. The MiPPS package owns the separate
bounded authentication oneshot. There is one MCA client and one PAN owner.
Old kernels without these parameters skip the policy unit, so booting the
previous set does not pass unknown module options to the old driver.

| Path | Input ceiling | Buck FCC ceiling |
|---|---:|---:|
| SDP / CDP | 500 / 900 mA | 500 / 900 mA |
| DCP, QC, Type-C and PD at 5 V | 1500 mA | 2000 mA |
| FLOAT / OCP | 1000 mA | 1000 mA |
| Fixed PD at 9 V | 1600 mA, bounded by PDO | 3000 mA |
| PD_VERIFY / PPS at 9 V | 2500 mA, bounded by PDO/APDO | 3000 mA |
| Unknown, reserved or unsupported | refused | refused |

Automatic Type-C/FLOAT ICL remains at the community fallback of 500 mA;
Type-C FCC also stays at 500 mA. The table lists ceilings, not forced targets.
The obsolete standalone ICL udev candidate is removed.

The battery-temperature policy only reduces FCC, with a delayed, stepped
recovery. SC8541 direct charging uses a PPS contract and both gauges; it starts
only below 4.10 V and in its narrower temperature window, leaves at 4.20 V or
45 °C, and stops on read/protection failures. Source, stage and combined-cell
limits are separate. These are the imported conservative software windows;
the stock board ceilings were checked on this unit. This is not complete
Android JEITA/FFC policy: float voltage and firmware thermal settings remain
untouched. The present package is for the bounded room-temperature test below,
not an all-temperature charging qualification. Do not interpret `Charging`,
service `active`, or an authentication result as net battery charge.

Authentication exchanges and exact provenance are in
[device/power/mipps-auth](../device/power/mipps-auth/README.md). It does not
promise 67 W. At high state of charge the stage may never enter direct charging;
record that path as unexercised rather than forcing it.

## Prepare and boot once (tech lead, later)

No commands below were executed on the tablet by this task. Reserve this unit,
keep the lead present, use its stock charger, and keep developer mode enabled.
Use the normal serial-bound project connection helper to transfer the bundle
and enter the installed Ubuntu shell. `PIANO_SERIAL` must identify this tablet.

1. On the current installed Ubuntu, unpack to `/var/tmp/charging3`, verify
   `sha256sum -c SHA256SUMS`, then run:

   ```sh
   sudo python3 /var/tmp/charging3/charging-test-device.py \
     --serial "$PIANO_SERIAL" --preflight-only
   sudo piano-boot-switch verify
   sudo test ! -e /var/lib/piano/charging3-previous
   sudo cp -a /var/lib/piano/switch/ubuntu /var/lib/piano/charging3-previous
   ```

   The preflight requires both batteries at 40–90%. `--allow-high-soc` overrides
   only the upper guard and must also be passed to the observation below; at
   100% the rising-percentage PASS criterion cannot be met. Do not bypass the
   lower guard. Preserve the previous set and its kernel package on both the
   tablet and recovery host before installing the candidate.

2. Install the bundle's `piano-mipps-auth`, `piano-device-support` and complete
   `linux-image-7.2.6-piano8` debs together, using native APT. This is an
   installation step for the lead, not a step this offline task performed:

   ```sh
   sudo apt-get install /var/tmp/charging3/debs/*.deb
   sudo dpkg --audit
   sudo piano-boot-update 7.2.6-piano8
   sudo piano-boot-switch verify
   sudo piano-boot-switch to-ubuntu --dry-run
   sudo piano-boot-switch to-ubuntu --reboot
   ```

   The existing hook generates the matching dracut initrd and boot set and may
   already update slot A when Ubuntu owns it. Verify the result before reboot.
   No repartitioning, other slot, calibration or firmware replacement is needed.
   The bundle's prepared `piano-boot.dtb` is included in the kernel deb; do not
   reuse an earlier DTB, since this candidate adds SC8541 on this unit's SE5.

3. After this one cold boot, verify `uname -r` is `7.2.6-piano8` and the loaded
   kernel/config match the bundle manifest. Mount debugfs if needed. Start the
   bounded collector while still connected to the host:

   ```sh
   sudo mount -t debugfs debugfs /sys/kernel/debug 2>/dev/null || true
   sudo systemd-run --unit=charging3-test --collect \
     --property=RuntimeMaxSec=13min \
     --property="ExecStopPost=/var/tmp/charging3/revert.sh $PIANO_SERIAL /var/lib/piano/charging3-previous" \
     /usr/bin/python3 /var/tmp/charging3/charging-test-device.py \
     --serial "$PIANO_SERIAL" --attended-wall-charger --community-policy \
     --output /var/log/piano-charging3-01
   ```

   Move the cable to the stock wall charger within 120 seconds. The host USB
   connection disappears; the local service continues. It records ten minutes
   of policy operation without manually setting ICL/FCC. A lead must still
   supervise startup/recovery; the timer cannot recover an early kernel hang.

4. `ExecStopPost` imports the saved previous set through `piano-boot-switch`
   and boots it. It runs on normal completion, failure or collector timeout.
   After return, verify piano7, the old module/config and slot identity, then
   retrieve `/var/log/piano-charging3-01/` through the serial-bound helper.
   If the candidate cannot start the service, use the existing host
   `tools/piano-switch.py --serial <SERIAL> --images <saved-previous-set>
   --rollback <saved-candidate-set>` recovery flow from Fastboot. Never infer
   recovery success from an elapsed timeout.

## PASS and capture

PASS requires recognized PD/PPS, measured voltage/current consistent with the
negotiated path and this unit's ceilings, both battery currents positive in the
last-minute median, mean percentage rising, both battery temperatures within
15–45 °C throughout, and a current-boot `pd_auth=1` journal entry with verified
readback. Preserve samples even when percentage is unchanged; that is not PASS.

Capture `samples.jsonl`, result/identity/boot ID, phase-boundary MCA
status/stats/frames, authentication journal and relay values, SC8541 state,
and dmesg. Review transport errors, protection trips, resets and cooling
transitions manually as well as the collector result. SC8541 engagement,
physical attach/detach, hardware protections and recovery are separate
observations; do not inherit their PASS from QEMU.

**Revert:** boot the saved previous set using the bundle's `revert.sh` or the
existing recovery flow above. Keep the previous kernel installed. Restoring the
previous support package is also appropriate when ending evaluation; the new
units skip the old kernel and do not enable the new policy there.

Unverified by the offline package: actual GLINK/PD/VDM exchanges, effective
limits, net charging, real temperatures, SC8541 I2C and analog protections,
stock charger/cable behavior, boot-set update on this installed root, and
physical recovery. The software kick uses kernel work and is not a hardware
watchdog guarantee during a hard lockup.
