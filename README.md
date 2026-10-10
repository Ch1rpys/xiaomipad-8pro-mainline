# Ubuntu for Xiaomi Pad 8 Pro

Run Ubuntu 26.04 LTS with GNOME on the Xiaomi Pad 8 Pro (`piano`, SM8750P) alongside Android, with a device-adapted kernel based on upstream Linux 7.2. [中文](README.zh-CN.md)

## Latest Release and Recent Updates

**[v0.1.0-preview](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.1.0-preview)** (developer preview, kernel 7.2.6-piano5): the Ubuntu boot image set (`boot`, `init_boot`, `vendor_boot`), the root filesystem image, the maintenance RAM image, the firmware and device packages, the switching and recovery tools, and manual installation steps ([docs/INSTALL.md](docs/INSTALL.md)). Download every `piano-v0.1.0-preview.tar.zst.part*` and restore the release directory with `cat piano-v0.1.0-preview.tar.zst.part* | zstd -d | tar -x` (about 14 GB of free space), then `sha256sum -c SHA256SUMS` inside it. Automated installation will follow in a later version.

Recent updates:

- **Dual boot**: Ubuntu is installed next to Android on the test unit. Switching from Ubuntu to Android and marking slot A as successfully booted are verified on the device.
- **Kernel 7.2.6-piano5**: upstream versions of the ADSP, PCIe and Adreno 830 changes, CPU thermal throttling at the stock temperatures, a tablet-mode switch from the keyboard dock, and both backlight controllers under one `ktz8866-backlight` device (brightness via sysfs; no GNOME slider yet). The internal microphones record through the VA path; a 1 kHz test tone played near the tablet was recorded by all four.
- **Wi-Fi 5 GHz**: with kernel 7.2.6-piano4 NetworkManager's scans on the test unit find 5 GHz networks as well as 2.4 GHz ones; connecting is not yet verified.
- **Kernel 7.2.6-piano3**: Wi-Fi now loads its firmware from the installed system, uses this unit's MAC address and scans; read-only charger input reporting and several boot-log fixes are included.
- **Kernel 7.2.6-piano2**: the display clock controller is built in, which fixes boots that ended in a black screen or in GPU and touch timeouts.
- **Developer mode**: optional SSH over the USB cable for maintenance, off by default and verified on the device.
- **In progress**: Wi-Fi association with a network, and charge control.

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
- **No charging under Linux**: the battery discharges even with USB connected. Charge in Android and keep at least 40 % before switching.
- **Recovery**: with no picture or no response, hold Power + Volume Down to enter Fastboot and switch to Android with `tools/piano-switch.py` (see [Usage and Maintenance](#usage-and-maintenance)). Release images have no debug console.
- **Unofficial and experimental**: not affiliated with Xiaomi. Only for the Xiaomi Pad 8 Pro (`piano`, SM8750P), tested on one unit: model 25091RP04C (China), 16 GB RAM, 512 GB UFS. Other variants and capacities are untested.

The 512 GB layout splits the original `userdata` range into `userdata` (200 GiB, Android), `linux_rootfs` (60 GiB, Ubuntu `/`) and `linux_data` (about 201.27 GiB, `/home`); other partitions and LUNs are unchanged.
Never flash `vbmeta`, write slot B or make it active: on the test unit slot B holds an older stock chain that does not boot Android. Android OTA updates are untested.
Calibration data and the Bluetooth address must come from your own tablet; never copy them between devices.

## 🚀 Getting Started

1. **Use a release**: [v0.1.0-preview](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.1.0-preview); download and restore as in [Latest Release](#latest-release-and-recent-updates), then follow [docs/INSTALL.md](docs/INSTALL.md). Its contents and the pipeline that builds them are in [docs/RELEASE.md](docs/RELEASE.md).
2. **Build from source**: inputs are pinned in [kernel/source.json](kernel/source.json) and [kernel/abi.json](kernel/abi.json) (kernel commit, configuration fragments, release), [mesa/source.json](mesa/source.json) (Mesa 26.2.0 and its A830 patch), [ubuntu/](ubuntu/26.04.sources) (official 26.04 Desktop ARM64 ISO, snapshot APT sources) and `device/*/source.json`. The tools in [tools/](tools/) build the kernel package, Mesa, the device packages, the ext4 root image and the signed boot image set without root privileges. Touch calibration, Bluetooth address, boot profile, stock DTB and DTBO and an AVB signing key come from your own tablet and are never committed. Details: [docs/BUILD.md](docs/BUILD.md).
3. **Install**: follow the manual steps in [docs/INSTALL.md](docs/INSTALL.md); switching, Fastboot recovery and what never to flash are in [docs/FLASHING.md](docs/FLASHING.md).

Do not mix files from different builds: the kernel image and its modules must come from the same build.

<a id="support-matrix"></a>

## Hardware Support

Status on the test unit with kernel 7.2.6-piano5, as of 2026-10-10; other variants and accessories are not implied tested.
Test configuration, known issues and roadmap: [docs/STATUS.md](docs/STATUS.md).

✅ Working · 🟡 Partial · ❌ Unsupported · 🧪 Unverified

✅ marks results verified on the device. *Test build* marks results from diagnostic boots that are not yet in 7.2.6-piano5.

### Platform, Display and Input

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| SoC / CPU | Qualcomm Snapdragon 8 Elite (SM8750P), ARM64 | ✅ Working | SCMI frequency scaling on all eight cores |
| Boot | Xiaomi ABL / AVB, slot A | ✅ Working | Owner-signed v4 image set; slot marked successful after each boot; `vbmeta` unchanged |
| Dual-boot switching | `piano-boot-switch`, slot A image sets | 🟡 Partial | Switching from Ubuntu verified; app-grid button and Android-side module unverified |
| Internal storage | KIOXIA UFS / ext4 | ✅ Working | 60 GiB root and about 201 GiB `/home` |
| Display | Bootloader framebuffer / simpledrm | 🟡 Partial | 3200×2136 at 120 Hz; no native driver, so fixed brightness and no screen-off or wake; occasional flicker with touch active |
| GNOME desktop | Ubuntu 26.04 GNOME / Wayland / GDM | ✅ Working | GPU-composited, 200 % scaling |
| GPU | Adreno 830 / msm / Mesa 26.2.0 + patch (`piano-mesa`) | ✅ Working | OpenGL ES; Ubuntu's Mesa 26.0.3 lacks A830 support; Vulkan, sustained load and GPU power management unverified |
| Touchscreen | Novatek NT36532E / SPI / `piano-thp` | 🟡 Partial | Single-finger input, correct orientation; no long press; lock-screen on-screen keyboard fails; multi-touch, edges and power management unverified |
| Stylus | Novatek NT36532E pen scanning | ❌ Unsupported | Pen scanning is turned off when touch starts |
| Magnetic keyboard | Nanosic WN8030 I2C bridge / `hid-nanosic` | 🟡 Partial | Keys work; reattach and power management unverified; the tested keyboard has no touchpad |
| Fingerprint | — | ❌ Unsupported | No driver |

### Wireless and USB

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Wi-Fi | Qualcomm WCN7860 / PCIe / ath12k | 🟡 Partial | Firmware load, MAC address and 2.4/5 GHz scanning verified; association not yet verified |
| Bluetooth | Qualcomm WCN7860 / UART / `hci_qca` | 🟡 Partial | Firmware, power-on and device discovery; pairing, audio and Wi-Fi coexistence unverified |
| USB device mode | Synopsys DWC3 / USB 2.0 NCM | ✅ Working | SSH over USB in developer mode, off by default; no other USB function in release images |
| USB host / Type-C roles | UCSI | ❌ Unsupported | Type-C role switching not enabled |
| USB-C external display | DisplayPort Alt Mode / DIO4485 | ❌ Unsupported | Needs the native display driver; DP and DIO4485 nodes disabled |

### Audio, Video and Sensors

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Speakers | 4 × FS19xx-family amplifiers | ❌ Unsupported | No mainline driver; no playback device |
| Microphone | Internal DMIC / ADSP / AudioReach | 🟡 Partial | Records through the VA path with a UCM profile; a 1 kHz test tone was picked up by all four microphones; speech quality and noise processing unverified |
| Video decoding | Qualcomm Iris (VPU35) | ❌ Unsupported | Built as modules, not enabled |
| Cameras | S5KJN1SQ03 rear, OV32D40 front | ❌ Unsupported | Mainline lacks SM8750 CAMSS support |
| Rotation, light and Hall sensors | ADSP sensor hub (SSC) | ❌ Unsupported | Userspace stack prepared, not enabled |

### Power and Time

| Feature | Component / Implementation | Status | Scope and Limitations |
|---|---|---|---|
| Power / volume keys | Qualcomm PMIC | 🟡 Partial | Power key reaches logind; no screen-off or wake; volume keys unverified |
| Battery gauges / thermal | 2 × TI BQ27Z561 / thermal zones | ✅ Working | Capacity, voltage and current; thermal zones readable; throttling unverified |
| Charging | Xiaomi MCA charger via ADSP | 🟡 Partial | Read-only USB input reporting; no charge control; the battery discharges under Linux, also on USB |
| Suspend | Linux power management | ❌ Unsupported | Disabled by policy until suspend and resume are validated |
| Hibernation | — | ❌ Unsupported | The layout has no swap partition |
| Real-time clock | PMK8550 RTC | ❌ Unsupported | Not writable; the clock is wrong after each boot until set or synced |

## Usage and Maintenance

Details: [docs/FLASHING.md](docs/FLASHING.md) (switching, slot attributes, recovery).

**Switching systems.** In Ubuntu, `sudo piano-boot-switch to-android --reboot` writes the stored Android set to slot A, reads it back and restarts (verified on the device); the **Switch to Android** app-grid entry runs the same tool but is not yet verified.
From Android, the KernelSU module in [device/android/piano-switch-ksu](device/android/piano-switch-ksu/README.md) switches to Ubuntu; it is not yet verified on the device, so use the host path below until it is.
Switching inside either system keeps the slot attributes.

**Recovery from the host.** In Fastboot (Power + Volume Down), `tools/piano-switch.py` checks the device and both image sets, writes slot A and restores the previous set if a write fails:

```sh
python3 tools/piano-switch.py --serial <serial> --images <android-set> --rollback <ubuntu-set>
fastboot -s <serial> reboot
```

A host write resets slot A's retry counter, and `piano-slot-success` marks the slot again after the next Ubuntu boot. If Fastboot shows `slot-unbootable:a` = `yes`, `fastboot -s <serial> --set-active=a` resets it; slot B stays unusable. See [device/boot](device/boot/README.md).

**Updating the kernel.** `sudo dpkg -i linux-image-<release>_*.deb` runs dracut and `piano-boot-update`, which rebuilds the Ubuntu image set and rewrites slot A in place when it holds Ubuntu (about 12.5 minutes on the device); reboot to use it. Otherwise `sudo piano-boot-switch to-ubuntu` writes the new set.

**Developer mode.** `sudo piano-devmode on` adds SSH over the USB cable (USB NCM, tablet at 192.168.88.2); it is off by default and needs `openssh-server`. From the host, `python3 tools/piano-devmode-ssh.py USER` connects about 22 s after boot. See [device/devmode](device/devmode/README.md).

**Time after boot.** The PMIC RTC cannot be written, so the clock is wrong after every boot. Set it manually, for example `sudo date -s '2026-10-09 18:00'`, or let network time correct it once the tablet is online.

## Development and Contributions

| Repository | Contents |
|---|---|
| xiaomipad-8pro-mainline | Device userspace, Ubuntu integration, build, packaging and switching tools, firmware, documentation |
| [linux-sm8750-piano](https://github.com/yzddmr6/linux-sm8750-piano) | Linux kernel: drivers, device trees and configuration on the upstream v7.2.6 stable history, branch `piano/dev` |

[kernel/source.json](kernel/source.json) pins the kernel commit and configuration fragments; [kernel/abi.json](kernel/abi.json) gives every packaged build a unique release (`7.2.6-piano5` is current).
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
