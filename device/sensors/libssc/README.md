# SSC reference input

Use upstream libssc at the commit in `source.json`, apply its hash-checked patch,
and build with upstream Meson. The patch only corrects the test wrapper's exit
status: an actual child failure with status 7 returned 0 before, and 7 after.
The focused regression substitutes the QRTR availability check and opens no DSP
socket. It does not validate sensor messages.

The patched source builds for ARM64 with a matching target sysroot. If the cross
compiler searches its host-installed cross libc first, give Meson explicit target
library search directories and verify its effective `c_link_args`; editing a
machine file and reconfiguring does not override cached built-in options.

The compatible iio-sensor-proxy input and its hash-checked patches are pinned
separately in `sensorproxy.json`. Apply those patches to that upstream checkout
and use the original Meson build with `-Dssc-support=enabled`. Use its existing
service, D-Bus API and rules. SSC accelerometer/proximity rules remain disabled
upstream; these changes do not enable physical rotation.

The four C patches are reused unchanged from the liuqin integration snapshot
identified in the lock and `NOTICE`. They start sensors claimed during coldplug
and broadcast availability to observers before claims. Releasing a pending
claim completes that sender's call with a cancellation error while retaining
other clients' claims. Measurement notifications remain directed to claimants.
The accelerometer patch serializes polling transitions while libssc synchronous
operations dispatch nested Claim/Release calls. The full pinned series passes
the ARM64 QEMU SensorProxy suite (four groups, including two release cases)
and all three polling cases.
No board identity, SLPI service policy, calibration
or mounting matrix is imported. The test patch waits for the resulting capability
notification using the existing assertion deadline, keeping functional checks
and the upstream disabled tests.

The full Ubuntu test stopped during startup/APT preparation. A QEMU-only
runtime using the checked package data directly passes seven libssc protocol
groups and two software matrix/orientation groups. Three targeted SensorProxy
checks pass: an early light claim
starts sampling once, light readings reach D-Bus, and compass availability is
announced. Unclaimed broadcasts are checked to contain no light/heading readings.

The pending-release fix also passes two scenarios on the upstream synthetic IIO
buffer: cancel before the first reading and reopen, and cancel one of two clients
while the other continues to receive data. The three SSC checks pass with this
new daemon too. These cases exercise the common D-Bus ownership layer; they do
not establish SSC-internal task cancellation, sensor power-down or suspend.

These are real ARM64 programs using a local QRTR namespace, private D-Bus and
upstream synthetic sensors. The raw package-data runtime does not verify APT
installation or normal Ubuntu startup. No service or replacement system library
has been installed on the host or tablet, and no physical sensor result is claimed.
libssc remains GPL-3.0-or-later; see its file notices and
`LICENSES/hexagonrpc-GPL-3.0.txt` for the shared GPL v3 license text.
SensorProxy's C and test-file licenses are listed separately in `NOTICE`.
