# Piano camera first-frame candidate

The MIT `piano-camerad.c` was imported byte-for-byte from blu-sharky/debian-piano
`a75f8c5d5fa099d65c171ac839c2e3bb6c63ec45`, with its three original camera commits
and author history retained. The separate local fixes provide a writable CCM
payload and ACTIVE format/flip checks. `source.json` records the original and
current hashes, the unchanged community WirePlumber policy, and the GPL-2.0-or-later
v4l2loopback v0.15.4 revision selected by that project's CI. the repository `NOTICE` and camera `LICENSE`
preserve attribution. The loopback module is compiled against the candidate's
complete kernel OUT, not through DKMS. No camera firmware is required by this
CAMSS/TFE/sensor path.

Loopback publication defaults to `PIANO_CAMERA_OUTPUT=bgrx`; set
`PIANO_CAMERA_OUTPUT=nv12` in `/etc/piano/camera.conf` to restore NV12 (the
service reads this optional environment file). ISP capture stays full-range
BT.601 NV12; a local integer conversion publishes sRGB BGRx, including black
bootstrap frames. This bounds a workaround for the lead-verified 2026-10-15
GTK 4.22 GL/Vulkan diagonal stripes on Mesa 26.2.0 / Adreno 830: raw NV12,
GStreamer software paths and GTK cairo render correctly, as do RGB textures.
Remove the conversion/default workaround once Mesa renders two-plane NV12
textures correctly on A830, verified in GTK GL and Vulkan on this device.
This offline change has not itself been tested on the tablet.

The fourcc is `V4L2_PIX_FMT_XBGR32` (`XR24`), whose bytes are B,G,R,x.
PipeWire 1.6.2 (`95da54a482b68475958bbc3fa572a9c20df0df74`)
`spa/plugins/v4l2/v4l2-utils.c` maps it to `SPA_VIDEO_FORMAT_BGRx`;
`src/gst/gstpipewireformat.c` maps that to GStreamer's BGRx (format index 8,
also checked against the installed GStreamer 1.24.2 library).

Host-only conversion test and 1920×1440 timing (no camera access):

```sh
gcc -O2 -fvect-cost-model=cheap -Wall -Wextra -Werror \
  device/camera/test-nv12-bgrx.c -lm -o /tmp/test-nv12-bgrx
/tmp/test-nv12-bgrx
/tmp/test-nv12-bgrx --timing
```

AArch64 builds use 16-pixel NEON conversion with scalar tails and a non-AArch64
scalar fallback; exhaustive byte-exact YUV, random padded-stride/tail and independent
BT.601 checks passed on x86 and AArch64 QEMU (correctness only).
On the tablet the NEON path converts a 1920x1440 frame in 1.9 ms (scalar: about 10.6 ms); with the rear camera at about 31 fps in Snapshot, camerad uses about 19 % of one core, compared with 37 % for the scalar BGRx path and 4 % when publishing NV12.
The first-frame diagnostic explicitly selects NV12 to retain its existing analysis format.

Build with the project's cross compiler after `tools/build-kernel.sh` finishes:

```sh
python3 tools/build-camera-debs.py --kernel-out <kernel-out> \
  --loopback-source <clean-pinned-v4l2loopback-checkout> --output <new-output-dir>
```

The output contains separate `piano-camerad` and
`piano-camera-loopback-<kernel-release>` packages, the ARM64 daemon, the actual
`.ko`, a source archive, payload hashes, and `SHA256SUMS`. Only the module package
runs depmod during installation/removal. The camerad package enables and starts its notify service; the module package
does not start a camera. Normal OF coldplug loads camera drivers from the kernel
package. The kernel uses translated DMA by default; the community overlay's
manual IOMMU-domain switch is therefore unnecessary. The unchanged community WirePlumber policy disables the libcamera monitor and
hides raw CAMSS devices, leaving the loopbacks for applications. It is installed
as vendor configuration under `/usr/share/wireplumber/wireplumber.conf.d/`.
Reboot or restart each active user WirePlumber instance after installing it,
including any GDM greeter instance, before starting camerad. No fixed account,
global module blacklist or Debian rootfs orchestration is imported.

After the project lead schedules device validation, keep the installed piano17
kernel package and independently save its verified boot triplet on tablet and
host. Follow [UPGRADE](../../docs/UPGRADE.zh-CN.md) for the existing APT/dracut/ABL
update hooks; installing the kernel package updates the boot set. Install all
three candidate debs together; the root must have Python 3, NumPy, v4l-utils,
procps and kmod (normal distribution packages). Reboot into the exact new release.

```sh
sudo piano-camera-test --expected-release 7.2.10-piano20 \
  --output /var/tmp/piano-camera-first-frame
```

Run on the tablet as root. The script checks ARM64, `xiaomi,piano`, the running
release and translated CAMSS DMA domain. The installed kernel build receipt is
optional for RAM boot on the piano17 root; if present its release must match.
The running kernel version, boot ID and live FDT hash are always recorded. It enumerates every media graph, then
uses the community daemon with the recorded fixes to drive the sensors/TFE and feed its two
1920×1440 NV12 loopbacks. It captures front and rear sequentially, 30 frames each,
within 30 seconds per camera. Initial synthetic zero-luma loopback frames are
excluded and one is retained as `bootstrap.nv12`; sensor test patterns are refused.
Every counted full-range JPEG/NV12 frame must have luma mean >1 and standard deviation >1, and at
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
then unloads its own loopback module. An unavailable optional VCM is recorded as a warning and cannot prevent sensor
capture; piano20 disables the unverified GT9764BA node and does not test AF.
A restoration error fails the overall result. INT/TERM/HUP take the same cleanup path; SIGKILL, power loss or a wedged
kernel cannot guarantee userspace cleanup. On an already running camera setup,
close it explicitly before running this first-frame test.

For a kernel with the GT9764 actuator enabled, add `--focus-sweep`:

```sh
sudo piano-camera-test --expected-release 7.2.10-piano22 --focus-sweep \
  --output /var/tmp/piano-camera-focus
```

Keep the tablet and a lit, textured subject stationary. After the usual captures,
the test stops its own camerad so its AF/AE cannot compete, then captures the
same rear CAMSS NV12 source directly with v4l2-ctl. It queries focus min/max/step,
uses five legal positions including both legal endpoints, waits 100 ms per move,
and discards four startup frames from each fresh stream before saving three.
The wait exceeds the driver's default 6.65 ms move delay (+1 ms allowance) and
the community AF's two 30 Hz frames; it is not a measured GT9764 settling bound.
The lens fd stays open to prevent runtime-PM parking between positions.

`cameras.rear.focus_sweep` records controls, frame paths/hashes, per-frame centre-third
horizontal gradient energy divided by luma (the community AF metric), and the
median at each position. Every write/readback must match, exposure/gain must
remain fixed, and max/min sharpness must be at least 1.3 for PASS. Matching controls
with a smaller ratio give FAIL: “执行器写入被接受但图像无变化”. Missing controls or failed
writes/captures give FAIL. If all medians are below the conservative noise/texture
gate of 1.0 in 8-bit metric units, the result is INCOMPLETE, never PASS. This gate
is not calibrated sensor noise; motion/lighting changes can invalidate the scene.
Overall INCOMPLETE exits nonzero, as does FAIL. The common restore restores and
reads back the original focus and other state, including on a failed sweep.
This test establishes focus-dependent image change, not autofocus accuracy.

To roll back while Ubuntu still runs:

```sh
sudo piano-boot-switch import-ubuntu --from /var/lib/piano/rollback-7.2.9-piano17
sudo piano-boot-switch to-ubuntu --reboot
```

Confirm `uname -r` is `7.2.9-piano17` before removing the candidate packages.
If it cannot boot, use the independently saved piano17 triplet and the existing
serial-bound recovery tool described in [FLASHING](../../docs/FLASHING.zh-CN.md).
Device installation and capture have not been run during offline preparation.
