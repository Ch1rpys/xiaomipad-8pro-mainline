# Ubuntu for Xiaomi Pad 8 Pro

Run Ubuntu 26.04 LTS with GNOME on the Xiaomi Pad 8 Pro (`piano`, SM8750P) alongside Android, with a device-adapted kernel based on upstream Linux 7.2. [中文](README.zh-CN.md)

**Latest kernel/package release: 7.2.6-piano9 (ABI 9), device-verified on 2026-10-12.** See the [piano9 upgrade and acceptance record](docs/PIANO9.md).

## 📮 Follow & Discuss

Progress updates, usage tips and AI discussions (primarily in Chinese) are published here first — issue feedback is welcome.

| WeChat: 熵减矩阵 | Xiaohongshu: yzddmr6 |
|:---:|:---:|
| <img src="docs/assets/gzh-qr.png" width="200" alt="WeChat: 熵减矩阵"> | <img src="docs/assets/xhs-qr.jpg" width="200" alt="Xiaohongshu: yzddmr6"> |
| Updates · Tips · AI talks | Sharing · Feedback |

## ⚠️ Read Before Installing

- **Data loss**: installation re-creates `userdata` and clears `metadata`. All Android data on the tablet is erased.
- **Unlocked bootloader**: required, through Xiaomi's official process. Locked bootloaders are unsupported.
- **Stock build OS3.0.303.0.WPYCNXM on slot A**: the boot images copy its header fields, rollback indices and AVB properties, and the boot DTB is built against its DTB and DTBO. Other builds are unsupported.
- **Back up first**: back up every partition and the GPT of each UFS LUN before any write (reading partitions needs root in Android); `userdata` can be skipped because it is erased. Slot A's stock `boot`, `init_boot` and `vendor_boot` are your way back to Android.
- **Net charging is not verified under Linux**: `xiaomi_mca` provides read-only reporting; MiPPS/charging3 control still needs the wall-charger test. Charge in Android and keep at least 40 % before switching.
- **Speaker protection is absent**: FS19xx playback is verified with a −15 dB cap; protection remains open (TD-026).
- **Suspend is disabled** by product policy (D3); the RTC cannot be set (TD-022).
- **Recovery**: with no picture or no response, hold Power + Volume Down to enter Fastboot and switch to Android with `tools/piano-switch.py` (see [Usage and Maintenance](#usage-and-maintenance)). Release images have no debug console.
- **Unofficial and experimental**: not affiliated with Xiaomi. Only for the Xiaomi Pad 8 Pro (`piano`, SM8750P), tested on one unit: model 25091RP04C (China), 16 GB RAM, 512 GB UFS. Other variants and capacities are untested.

The 512 GB layout splits the original `userdata` range into `userdata` (200 GiB, Android), `linux_rootfs` (60 GiB, Ubuntu `/`) and `linux_data` (about 201.27 GiB, `/home`); other partitions and LUNs are unchanged.
Never flash `vbmeta`, write slot B or make it active: on the test unit slot B holds an older stock chain that does not boot Android. Android OTA updates are untested.
Calibration data and the Bluetooth address must come from your own tablet; never copy them between devices.
For sensors, stage the private registry calibration from your own backup with
[tools/stage-sensor-registry.py](tools/stage-sensor-registry.py), following the
[sensor package instructions](device/sensors/README.zh-CN.md#原厂配置与私有标定).

## 🚀 Getting Started

The support table describes the installed piano9 system. The preview download below is an earlier installation image; check its package versions separately. For a piano8-to-piano9 upgrade, follow [docs/PIANO9.md](docs/PIANO9.md) and preserve `piano9-rollback`.

1. **Use a release**: [v0.1.0-preview](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.1.0-preview). Download SHA256SUMS.assets and every asset listed in it from the same release into an empty directory. This release has two archive parts, `piano-v0.1.0-preview.tar.zst.part0` and `piano-v0.1.0-preview.tar.zst.part1`. Run `sha256sum -c SHA256SUMS.assets` there and require every entry to pass before extracting the archive parts. Restore with `cat piano-v0.1.0-preview.tar.zst.part* | zstd -d | tar -x` (about 14 GB free space), run `sha256sum -c SHA256SUMS` inside the extracted directory, then follow [docs/INSTALL.md](docs/INSTALL.md). Its contents and the pipeline that builds them are in [docs/RELEASE.md](docs/RELEASE.md).
2. **Build from source**: inputs are pinned in [kernel/source.json](kernel/source.json) and [kernel/abi.json](kernel/abi.json) (kernel commit, configuration fragments, release), [mesa/source.json](mesa/source.json) (Mesa 26.2.0 and its A830 patch), [ubuntu/](ubuntu/26.04.sources) (official 26.04 Desktop ARM64 ISO, snapshot APT sources) and `device/*/source.json`. The tools in [tools/](tools/) build the kernel package, Mesa, the device packages, the ext4 root image and the signed boot image set without root privileges. Touch calibration, Bluetooth address, boot profile, stock DTB and DTBO and an AVB signing key come from your own tablet and are never committed. Details: [docs/BUILD.md](docs/BUILD.md).
3. **Install**: follow the manual steps in [docs/INSTALL.md](docs/INSTALL.md); switching, Fastboot recovery and what never to flash are in [docs/FLASHING.md](docs/FLASHING.md).

Do not mix files from different builds: the kernel image and its modules must come from the same build.

<a id="support-matrix"></a>

## Hardware Support

Updated 2026-10-12 for the installed **7.2.6-piano9 (ABI 9)** system. Video decoding was checked in RAM with piano8 modules; touch orientation and keyboard keys were confirmed earlier by the user. Other variants and accessories are untested.
Test configuration, known issues and roadmap: [docs/STATUS.md](docs/STATUS.md).

✅ Working · 🟡 Partial · ❌ Unsupported · 🧪 Unverified

✅ means the stated function was verified on the device, not that every lifecycle or application was tested. Unchanged platform rows retain their earlier evidence. This table is authoritative for support status; release notes must retain the same limits.

### Platform, Display and Input

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| SoC / CPU | Qualcomm Snapdragon 8 Elite (SM8750P), ARM64 | ✅ Working | SCMI frequency scaling on all eight cores |
| Boot / kernel packages | Xiaomi ABL / AVB, slot A | ✅ Working | Piano8 → piano9 installed with `piano9-rollback`; [cold-boot acceptance passed](docs/STATUS.md#cold-boot-acceptance) |
| Dual-boot switching | `piano-boot-switch`, slot A image sets | ✅ Working | Image-set rotation and Android KernelSU module switching verified; clean shutdown on RAM-check return fixed |
| Internal storage | KIOXIA UFS / ext4 | ✅ Working | 60 GiB root and about 201 GiB `/home` |
| Display | Native DSI KMS / `msm_dpu` | ✅ Working | 3200×2136 at 144 Hz, backlight through Mutter and DPMS off/on hardware-verified; simpledrm is only for first light |
| GNOME desktop | Ubuntu 26.04 GNOME / Wayland / GDM | ✅ Working | Piano9 cold-boot acceptance passed; GDM at 12.7 s |
| GPU | Adreno 830 / msm / Mesa 26.2 | ✅ Working | Mesa deb and snap `gpu-2404` provider integration .3 verified; Firefox WebRender verified |
| Touchscreen | Novatek NT36532E THP / SPI / `piano-thp` | ✅ Working | Touch input verified; orientation confirmed earlier by the user |
| Stylus | Novatek NT36532E pen scanning | ❌ Unsupported | Pen scanning is turned off when touch starts |
| Magnetic keyboard | Nanosic WN8030 transport | ✅ Working | Keys confirmed earlier by the user; this keyboard has no touchpad |
| Fingerprint | — | ❌ Unsupported | No driver |

### Wireless and USB

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Wi-Fi | Qualcomm WCN7860 / PCIe / ath12k | ✅ Working | Stable 2.4 GHz and 5 GHz 80 MHz HE links verified on the installed kernel |
| Bluetooth | Qualcomm WCN7860 / UART / `hci_qca` | 🟡 Partial | Scan found 4 devices; pairing and audio unverified |
| USB device mode | Synopsys DWC3 / USB 2.0 NCM | ✅ Working | SSH over USB in developer mode, off by default; no other USB function in release images |
| USB host / Type-C roles | UCSI | ❌ Unsupported | Type-C role switching not enabled |
| USB-C external display | DisplayPort Alt Mode / DIO4485 | ❌ Unsupported | Control chain checked offline only; external display not supported yet |

### Audio, Video and Sensors

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Speakers | FS19xx-family amplifiers | 🟡 Partial | Playback verified without speaker protection, capped at −15 dB (TD-026) |
| Internal microphones | DMIC / ADSP / AudioReach / PipeWire | ✅ Working | PipeWire capture verified: 1 kHz tone 29–36 dB above the noise floor |
| Video decoding | Qualcomm Iris / V4L2 | 🟡 Partial | 1080p H.264 bit-exact vs software in a piano8-module RAM check; piano9 exposes `/dev/video0/1`; app playback unverified |
| Video encoding | Qualcomm Iris / V4L2 | 🧪 Unverified | Encoder node present; encoding not tested |
| Cameras | S5KJN1SQ03 rear, OV32D40 front | ❌ Unsupported | Stock read-only evidence captured; SM8750 CAMSS support missing |
| Accelerometer, gyro, light, proximity | SSC / hexagonrpcd / libssc | ✅ Working | Samples verified with `piano-sensors` and `piano-iio-sensor-proxy`; SensorProxy reports orientation |
| GNOME auto-rotation | SensorProxy / Mutter tablet mode | 🧪 Unverified | Only active with keyboard detached under Mutter's rule; physical four-orientation test pending |

### Power and Time

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Power / volume keys | Qualcomm PMIC | 🟡 Partial | Power key reaches logind; volume keys unverified |
| Battery gauges / thermal | 2 × TI BQ27Z561 / thermal zones | ✅ Working | Capacity, voltage and current; thermal zones readable; throttling unverified |
| Charging | Read-only `xiaomi_mca` / MiPPS | 🟡 Partial | MiPPS/charging3 control awaits the wall-charger test; net charging unverified |
| Suspend | Linux power management | ❌ Unsupported | Disabled by product policy (D3) |
| Hibernation | — | ❌ Unsupported | The layout has no swap partition |
| Real-time clock | PMK8550 RTC | ❌ Unsupported | RTC cannot be set (TD-022) |

## Usage and Maintenance

Details: [docs/FLASHING.md](docs/FLASHING.md) (switching, slot attributes, recovery).
For host commands, set REPO, RELEASE and WORK as in [INSTALL.md](docs/INSTALL.md#what-you-need)
and run them from WORK. Source tools use `"$REPO/tools/NAME"`; release files use `"$RELEASE/PATH"`.

**Switching systems.** In Ubuntu, `sudo piano-boot-switch to-android --reboot` writes the stored Android set to slot A, reads it back and restarts. From Android, the [KernelSU switch module](device/android/piano-switch-ksu/README.md) switches to Ubuntu. Slot-A image-set rotation and the Android module are device-verified; clean shutdown on RAM-check return is fixed.
Switching inside either system keeps the slot attributes.

**Recovery from the host.** In Fastboot (Power + Volume Down), `tools/piano-switch.py` checks the device and both image sets, writes slot A and restores the previous set if a write fails:

```sh
python3 "$REPO/tools/piano-switch.py" --serial <serial> --images <android-set> --rollback <ubuntu-set>
fastboot -s <serial> reboot
```

A host write resets slot A's retry counter, and `piano-slot-success` marks the slot again after the next Ubuntu boot. If Fastboot shows `slot-unbootable:a` = `yes`, `fastboot -s <serial> --set-active=a` resets it; slot B stays unusable. See [device/boot](device/boot/README.md).

**Updating to piano9.** Follow [docs/PIANO9.md](docs/PIANO9.md#b-install-on-the-ordinary-piano8-root): preserve the independent `piano9-rollback` set and install the matching kernel and accompanying packages together. GStreamer good/bad are now desktop package dependencies; their presence does not prove application-level hardware playback.

**Developer mode.** `sudo piano-devmode on` adds SSH over the USB cable (USB NCM); it is off by default and needs `openssh-server`. From the host, use `python3 "$REPO/tools/piano-devmode-ssh.py" --serial <SERIAL> USER`. The installation turns it on; turn it off afterwards with `sudo piano-devmode off` ([INSTALL.md](docs/INSTALL.md) step 10). See [device/devmode](device/devmode/README.md).

**Time after boot.** The PMIC RTC cannot be set (TD-022); check the system time after boot. The piano9 cold-boot result does not establish RTC support.

**Sensors and rotation.** Install `piano-sensors` and `piano-iio-sensor-proxy` and stage registry calibration from your own backup as described in the [sensor instructions](device/sensors/README.zh-CN.md). SensorProxy reports orientation, but Mutter enables automatic rotation only with the keyboard detached; the physical four-orientation test remains pending.

**After Initial Setup.** Initial Setup makes the user name the hostname unless you edit its *Computer* field; change it later with `sudo hostnamectl hostname --static <name>`. Run `sudo apt update` before the first `apt install`: the image has no current package indexes.

## Development and Contributions

| Repository | Contents |
|---|---|
| xiaomipad-8pro-mainline | Device userspace, Ubuntu integration, build, packaging and switching tools, firmware, documentation |
| [linux-sm8750-piano](https://github.com/yzddmr6/linux-sm8750-piano) | Linux kernel: drivers, device trees and configuration on the upstream v7.2.6 stable history, branch `piano/dev` |

[kernel/source.json](kernel/source.json) pins the kernel commit and configuration fragments; [kernel/abi.json](kernel/abi.json) gives every packaged build a unique release (currently `7.2.6-piano9`, ABI 9).
Device-specific inputs (calibration, Bluetooth address, boot profile, signing key, backups) belong to each owner and are never committed.
Debug image sets (`tools/build-persistent-boot.py --debug`) add a `fastboot boot` check image with an unauthenticated root shell over USB, for diagnostics only.

Before working on the device, read [docs/AGENT-GUIDE.md](docs/AGENT-GUIDE.md), written for human operators and AI agents alike. Contribution rules are in [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). No patch has been submitted upstream yet; candidates are listed in [docs/STATUS.md](docs/STATUS.md#upstreaming).

Report problems through [GitHub Issues](https://github.com/yzddmr6/xiaomipad-8pro-mainline/issues) with the device model, stock build, kernel release and image set identity; remove serial numbers, Bluetooth addresses, calibration data and personal information first.

## Acknowledgments and Licensing

This project reuses and adapts work from:
- the OnePlus Pad 2 Pro (`erhai`) mainline integration project (GPL-2.0-only; no public URL);
- the Xiaomi Pad 6 Pro (`liuqin`) mainline project: [integration](https://github.com/yzddmr6/xiaomipad-6pro-mainline) (MIT) and
  [kernel](https://github.com/yzddmr6/linux-sm8450-liuqin) (GPL-2.0);
- [BigfootACA/linux](https://github.com/BigfootACA/linux/tree/full-v7.1.3) (GPL-2.0);
- [ROCKNIX](https://github.com/ROCKNIX/distribution/tree/92a6fca6afda5ab7e1874af8985095beee19b6a8) and Teguh Sobirin's [SM8750 kernel patches](https://github.com/ROCKNIX/distribution/tree/92a6fca6afda5ab7e1874af8985095beee19b6a8/projects/ROCKNIX/devices/SM8750/patches/linux) (GPL-2.0; DTS BSD-3-Clause);
- Qualcomm (Jie Zhang, Akhil P Oommen, Gaurav Kohli): [Adreno 830 series](https://patchew.org/linux/20260809-pakala-gpu-v1-0-207ad1fac1c7%40oss.qualcomm.com/) (GPL-2.0);
- Junjie Cao: [NT36532 panel driver](https://patch.msgid.link/20260804074233.85629-1-junjie.cao@linux.dev) (GPL-2.0-only);
- Alexander Koskovich and Jonathan Marek: [DSC slices-per-packet patches](https://patch.msgid.link/20260318-dsi-dsc-slice-per-pkt-v2-1-0a1b316f8250@pm.me) (GPL-2.0);
- Xiaomi's [vendor_xiaomi_proprietary_touch-driver](https://github.com/MiCode/vendor_xiaomi_proprietary_touch-driver/tree/piano-w-oss) (GPL-2.0);
- ianchb's [xiaomi-sheng-thp](https://github.com/ianchb/xiaomi-sheng-thp) (Apache-2.0);
- map220v's [hid-nanosic-wn8030](https://github.com/ianchb/sm8550-mainline/blob/42f3b40c702abbc37c3a04c95af008cd283aeaf3/drivers/hid/hid-nanosic-wn8030.c) (GPL-2.0-only);
- AOSP [mkbootimg](https://android.googlesource.com/platform/system/tools/mkbootimg) (Apache-2.0) and
  [avbtool](https://android.googlesource.com/platform/external/avb/) (MIT);
- [Mesa](https://gitlab.freedesktop.org/mesa/mesa) (MIT);
- linux-msm [hexagonrpc](https://github.com/linux-msm/hexagonrpc) (GPL-3.0, LGPL-3.0) and
  [qrtr](https://github.com/linux-msm/qrtr) (BSD-3-Clause);
- [libssc](https://codeberg.org/DylanVanAssche/libssc) (GPL-3.0);
- [iio-sensor-proxy](https://gitlab.freedesktop.org/hadess/iio-sensor-proxy) (GPL-3.0);
- [AudioReach topology](https://github.com/linux-msm/audioreach-topology) (BSD-3-Clause);
- [TinyALSA](https://github.com/tinyalsa/tinyalsa) (BSD-3-Clause);
- [systemd](https://github.com/systemd/systemd) (LGPL-2.1-or-later, GPL-2.0-or-later);
- BusyBox (GPL-2.0);
- [Ubuntu](https://ubuntu.com/download/desktop).

Related projects, studied but not reused:
- [Project-SunUEFI](https://github.com/slwyts/Project-SunUEFI) (per-file licences);
- [blu-sharky/linux-piano](https://github.com/blu-sharky/linux-piano) (GPL-2.0);
- [blu-sharky/debian-piano](https://github.com/blu-sharky/debian-piano) (MIT).

Per-file sources, commits and changes are recorded in [NOTICE](NOTICE). Original integration code is
licensed under [MIT](LICENSE) unless a file's SPDX header states otherwise; several tools adapted
from GPL-2.0-only sources remain GPL-2.0-only. The kernel is GPL-2.0. Third-party components keep
their licences (see `LICENSES/`). The stock firmware in [firmware/](firmware/README.md) is
distributed unmodified from build OS3.0.303.0.WPYCNXM for interoperability. Its vendors have
granted no redistribution licence; it is not covered by the licences above and will be removed at
a rights holder's request. You can substitute firmware extracted from your own device with the
documented tool.
