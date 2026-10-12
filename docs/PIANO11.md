# Piano11: start touch after panel enable

Piano11 is the offline review revision of piano10, with a new ABI: **7.2.6-piano11**.
Piano10 and its ABI entry remain intact for the owner's early hardware comparison.
No piano11 device test has been performed by this task.
The kernel is `9ab0942f973489419d58caf5f69c17afee61df53`; ABI 11 binds its
exact configuration, leaving ABI 10 unchanged.

Offline checks: Image and 1271 modules compile without warnings; both piano
DTBs pass schema checks with zero diagnostics. ARM64 KUnit reports 167 PASS
and the same 4 SKIP as piano10: all 170 prior cases are unchanged, and the
new disabled-panel-open case passes. Host and ARM64 EPOCH regressions pass
with unchanged userspace. The 92,741,632-byte RAM image, its embedded ABL
identity and touch panel phandle, signed boot containers and all packaged
module versions pass readback checks. Real DPMS recovery remains untested.

NT36532E is a TDDI: panel power/prepare alone does not provide the display timing
needed by touch scanning. Waiting for a first frame from `panel_prepared` may
therefore expire before video starts. The driver now restarts the shared
firmware/first-valid-frame/BF-command sequence from `panel_enabled`, and stops
capture from `panel_disabling`. `panel_unpreparing` remains an idempotent stop
fallback. No prepared callback starts firmware.

Opening the misc device while the panel is disabled now succeeds: it claims
the exclusive reader, clears the FIFO and old error, and waits in poll. Panel
enable starts capture. This covers udev starting the `Restart=no` service before
the panel enables and reopening the stream while DPMS is off. If the panel is
already enabled when the follower registers, DRM immediately calls the enabled
callback and a subsequent open starts normally.

Firmware/startup failures still log errors and fail open or report an error to
an existing reader, without retries. Monotonic sequence numbers, EPOCH records,
partial-record preservation and system suspend policy are unchanged. Userspace
is unchanged; the existing mid-stream EPOCH regression is rerun on host and ARM64.
The additional KUnit case covers disabled-panel open/poll, exclusivity, repeated
stop and removal/close; it does not simulate hardware timing or physical input.

The local bundle contains the new matching kernel/modules deb, unchanged
piano10 support/auth/desktop/firmware debs with their original versions and
hashes, the bounded RAM image, persistent boot triplet and identity/checksum
receipts. Existing Mesa/sensor/Snap packages remain those of the installed root.
It contains per-device boot inputs and is not a public release artifact.

Hardware acceptance is reserved for Fable:

1. Preserve the known rollback boot set and kernel package; install the debs on
   ordinary Ubuntu, then run `sudo piano-boot-update 7.2.6-piano11` and verify
   the resulting boot set.
2. Cold boot and run `tools/piano-cold-boot-accept.py` with
   `--kernel-release 7.2.6-piano11`, the actual device serial and user.
3. With the panel off, reopen `piano-thp` and verify it stays alive waiting;
   enable the panel and require a new first-frame log and increasing `spi0.0`
   IRQ count. Also perform Mutter DPMS off/on without a service restart,
   keeping the same service PID and requiring those recovery indicators.
4. Ask the user to confirm physical finger input after the cycle.

No retry, delay, service restart policy or desktop workaround is introduced.
Repeated/long DPMS, actual video/IRQ sequencing, concurrent lifecycle stress,
suspend and physical gesture behavior remain unverified. TD-014 stays open.
