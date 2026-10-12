# Piano10: touch recovery after panel power cycles

Piano10 is an offline candidate, not a hardware-accepted release. It follows
piano9 (7.2.6, ABI 9) with ABI 10 and the NT36532E DRM panel follower.
Kernel source is `770e5fdd47de019a26992d91b79c69c7f13dde61`.

Offline checks passed: Image and 1271 modules with zero compiler diagnostics,
both piano DTBs with zero schema diagnostics, and ARM64 KUnit with 166 PASS
and the same 4 SKIP as piano9 (all 163 baseline cases retained, 7 THP firmware
cases added). The actual RAM image is 92,717,056 bytes; embedded DTB identity,
the touch-to-panel phandle, signed containers and packaged file hashes pass
readback checks. Host and ARM64/QEMU userspace EPOCH regressions also pass.

Panel unprepare resets the touch firmware in the shared TDDI. An open THP
stream now stops its IRQ before unprepare and reloads firmware after prepare,
using the same first-valid-frame and BF command sequence as open. A powered-off
panel makes new opens return EAGAIN; existing readers wait without a hangup.
Restart failures are logged and reported without retries. Stream sequence
numbers remain monotonic and the first valid queued frame carries EPOCH.
Partially read records are preserved across the transition.

The existing userspace EPOCH handler already releases contacts and resets the
processor and baseline. The new mid-stream test covers two active contacts,
contiguous sequence/time/counters, finger and non-finger first records, waiting
for a new baseline, and resuming input. It passes against the original code.
Removing EPOCH handling deliberately makes it fail; this mutation is not a
historical failure. No userspace processing change was necessary.

The local bundle contains the matching kernel/modules deb, current support,
MiPPS-auth, desktop and firmware packages, a bounded RAM-check image, and a
persistent boot triplet. The RAM image is smaller than 93,000,000 bytes and is
checked by extracting its embedded DTB, including the stock ABL identity.
The bundle contains per-device boot inputs and remains local.

Hardware acceptance is reserved for Fable after this offline task:

1. On ordinary installed Ubuntu, preserve an independent piano9 rollback boot
   set and retain the piano9 kernel. Install the bundle debs, then run
   `sudo piano-boot-update 7.2.6-piano10` and verify the generated boot set.
2. Cold boot and run `tools/piano-cold-boot-accept.py` with
   `--kernel-release 7.2.6-piano10`, the actual device serial and user.
3. Use Mutter DPMS off/on. Require the same `piano-thp` process to remain alive,
   `spi0.0` interrupt counts to resume increasing and a new
   `THP first frame after ...` line after panel prepare, without SPI errors or
   `THP panel restart failed`. Restarting the service is not acceptance.
4. Ask the user to confirm real finger input after the cycle.

No device access, package installation, boot or DPMS test is part of the
offline build. The full-module RAM initrd does not prove installed-root dracut
or cold-boot performance. System suspend remains unsupported for an open THP
stream; this change does not close all touch power-management or gesture work.
