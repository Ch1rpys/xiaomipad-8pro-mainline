# Piano camera first-frame candidate

The MIT `piano-camerad.c` is byte-for-byte from blu-sharky/debian-piano
`a75f8c5d5fa099d65c171ac839c2e3bb6c63ec45`, with its three original camera commits
and author history retained. `source.json` pins the source and the GPL-2.0-or-later
v4l2loopback v0.15.4 revision selected by that project's CI. `NOTICE` and `LICENSE`
preserve attribution. The loopback module is compiled against the candidate's
complete kernel OUT, not through DKMS. No camera firmware is required by this
CAMSS/TFE/sensor path.

Build with the project's cross compiler after `tools/build-kernel.sh` finishes:

```sh
python3 tools/build-camera-debs.py --kernel-out <kernel-out> \
  --loopback-source <clean-pinned-v4l2loopback-checkout> --output <new-output-dir>
```

The output contains separate `piano-camerad` and
`piano-camera-loopback-<kernel-release>` packages, the ARM64 daemon, the actual
`.ko`, a source archive, payload hashes, and `SHA256SUMS`. Only the module package
runs depmod during installation/removal. Neither package starts a camera or
enables a service. Normal OF coldplug loads camera drivers from the kernel
package. The kernel uses translated DMA by default; the community overlay's
manual IOMMU-domain switch is therefore unnecessary. No account, WirePlumber
policy, global module blacklist, or Debian rootfs orchestration is imported.

After the project lead schedules device validation, keep the installed piano17
kernel package and independently save its verified boot triplet on tablet and
host. Follow [UPGRADE](../../docs/UPGRADE.zh-CN.md) for the existing APT/dracut/ABL
update hooks; installing the kernel package updates the boot set. Install all
three candidate debs together; the root must have Python 3, NumPy, v4l-utils,
procps and kmod (normal distribution packages). Reboot into the exact new release.

```sh
sudo piano-camera-test --expected-release 7.2.10-piano19 \
  --output /var/tmp/piano-camera-first-frame
```

Run on the tablet as root. The script checks ARM64, `xiaomi,piano`, the running
release and translated CAMSS DMA domain. It enumerates every media graph, then
uses the unchanged community daemon to drive the sensors/TFE and feed its two
1920×1440 NV12 loopbacks. It captures front and rear sequentially, 30 frames each,
within 30 seconds per camera. Initial synthetic zero-luma loopback frames are
excluded and one is retained as `bootstrap.nv12`; sensor test patterns are refused.
Every counted frame must have luma mean >16.5 and standard deviation >1, and at
least two frame hashes must differ. These thresholds require a lit, textured
scene; a dark/flat scene can fail without indicating a driver defect.

`result.json` reports each camera independently, frame paths/hashes/statistics,
exposure lines, analogue gain and ISP digital gain. Control values are sampled
after receipt and are **not frame-synchronous sensor metadata**. `camerad.log`,
media graphs, kernel logs, original controls/formats/routes and `SHA256SUMS`
remain in the private output directory. A PASS is a first-frame/data-path result,
not an AE/AWB/AF, image-quality, motion, concurrent-camera or desktop-app result.

The test requires exclusive access and no pre-existing loopback/camerad. It
does not stop someone else's application/service. It stops its own capture and
daemon, restores formats, selections, controls and media links with readback,
then unloads its own loopback module. A restoration error fails the overall
result. INT/TERM/HUP take the same cleanup path; SIGKILL, power loss or a wedged
kernel cannot guarantee userspace cleanup. On an already running camera setup,
close it explicitly before running this first-frame test.

To roll back while Ubuntu still runs:

```sh
sudo piano-boot-switch import-ubuntu --from /var/lib/piano/rollback-7.2.9-piano17
sudo piano-boot-switch to-ubuntu --reboot
```

Confirm `uname -r` is `7.2.9-piano17` before removing the candidate packages.
If it cannot boot, use the independently saved piano17 triplet and the existing
serial-bound recovery tool described in [FLASHING](../../docs/FLASHING.zh-CN.md).
Device installation and capture have not been run during offline preparation.
