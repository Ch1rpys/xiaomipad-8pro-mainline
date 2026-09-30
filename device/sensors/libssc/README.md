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

The compatible iio-sensor-proxy input is pinned separately in `sensorproxy.json`.
Its existing SSC backend builds with `-Dssc-support=enabled`. Use its original
service, D-Bus API and rules. In this source, SSC accelerometer/proximity rules
remain disabled upstream; a successful build does not enable rotation.

Full tests in a disposable ARM64 Ubuntu guest stopped at the guest preparation
deadline before protocol checks began. Neither those tests nor piano sensors are
reported as passing. No service or replacement system library has been installed.
The original program remains GPL-3.0-or-later; see its file notices, `NOTICE` and
`LICENSES/hexagonrpc-GPL-3.0.txt` for the shared GPL v3 license text.
