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

The two C patches are reused unchanged from the liuqin integration snapshot
identified in the lock and `NOTICE`. They start sensors claimed during coldplug
and broadcast availability to observers before claims. Measurement notifications
remain directed to claimants. No board identity, SLPI service policy, calibration
or mounting matrix is imported. The test patch waits for the resulting capability
notification using the existing assertion deadline, keeping functional checks
and the upstream disabled tests.

The original full Ubuntu test stopped during startup/APT preparation. A later
QEMU-only runtime used the same checked package data directly: seven libssc
protocol groups and two software matrix/orientation groups passed. After the
startup fixes, three targeted SensorProxy checks passed: an early light claim
starts sampling once, light readings reach D-Bus, and compass availability is
announced. Unclaimed broadcasts are checked to contain no light/heading readings.
The earlier library checks were not repeated; the library/test bytes are unchanged.

These are real ARM64 programs using a local QRTR namespace, private D-Bus and
upstream synthetic sensors. The raw package-data runtime does not verify APT
installation or normal Ubuntu startup. No service or replacement system library
has been installed on the host or tablet, and no physical sensor result is claimed.
libssc remains GPL-3.0-or-later; see its file notices and
`LICENSES/hexagonrpc-GPL-3.0.txt` for the shared GPL v3 license text.
SensorProxy's C and test-file licenses are listed separately in `NOTICE`.
