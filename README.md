# Ubuntu for Xiaomi Pad 8 Pro

Native Ubuntu 26.04 LTS with the GNOME desktop on the Xiaomi Pad 8 Pro (codename `piano`, Snapdragon 8 Elite), dual-booting with Android, on a device-adapted kernel based on upstream Linux 7.2. Not a container, not a remote desktop. [中文](README.zh-CN.md)

**Latest release: [v0.6.0](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.6.0).** What works is in [Hardware Support](#hardware-support); the technical approach and how it differs from related projects is in [docs/APPROACH.zh-CN.md](docs/APPROACH.zh-CN.md) (Chinese).

## 📮 Follow & Discuss

Long-form technical articles, write-ups and progress updates are published on the WeChat official account; the community group is on Xiaohongshu — scan to join. Both are in Chinese, and installation feedback is welcome in either place.

<div align="center">
<table>
<tr><th>WeChat: 熵减矩阵</th><th>Xiaohongshu: yzddmr6</th></tr>
<tr>
<td align="center"><img src="docs/assets/gzh-qr.png" width="300" alt="WeChat: 熵减矩阵"></td>
<td align="center"><img src="docs/assets/xhs-qr.jpg" width="300" alt="Xiaohongshu: yzddmr6"></td>
</tr>
<tr><td align="center">Long-form articles · Write-ups · Updates</td><td align="center">Community group · Feedback</td></tr>
</table>
</div>

## ⚠️ Read Before Installing

- **This is an experimental project, not a daily driver.** Installing unlocks, repartitions and erases the tablet; a mistake can brick it, and recovery requires `adb`, `fastboot` and partition backups. Make sure you have the skills, decide deliberately, and accept the risk.
- **All Android data on the tablet is erased.** Installation re-creates `userdata` and clears `metadata`.
- **The bootloader must be unlocked** through Xiaomi's official process, and Android must be rooted (to read partitions for the backup).
- **Only stock build OS3.0.303.0.WPYCNXM on slot A is supported.**
- **Back up first.** Before any write, back up every partition except `userdata` and the partition table of every UFS LUN. Slot A's stock `boot`, `init_boot` and `vendor_boot` are your way back to Android.
- **Keep at least 40 % before switching systems.**
- **No speaker protection.** The speakers play, but with a capped volume; do not raise the gain yourself.
- **Verified on one unit only:** model 25091RP04C (China), 16 GB RAM, 512 GB storage. Other models and capacities are unverified.
- **Recovery:** with no picture or no response, hold Power + Volume Down for Fastboot and write Android back with `tools/piano-switch.py`, see [Usage and Maintenance](#usage-and-maintenance).

Partition layout: on the 512 GB model the original `userdata` range becomes `userdata` (200 GiB, Android), `linux_rootfs` (60 GiB, Ubuntu `/`) and `linux_data` (about 201 GiB, `/home`); nothing else changes.
**Never flash `vbmeta`, never write or activate slot B.** Calibration and per-unit configuration must come from your own tablet.

## 🚀 Installation

You need a Linux x86_64 host, a USB data cable, and an hour or two next to the tablet.

### Recommended: let an AI assistant install it

The procedure is long and order-sensitive. The easiest way is to hand it to an AI coding assistant that can run commands (Claude Code, Codex CLI, Gemini CLI, …). Start the assistant on the Linux host and paste the block below in full. It reads the documentation, checks the environment, makes the backup and asks for your confirmation before every write; you only press buttons on the tablet and make the choices.

```text
I want to install Ubuntu on a Xiaomi Pad 8 Pro (codename piano), dual-booting with Android. Act as my operator and follow these rules.

Project: https://github.com/yzddmr6/xiaomipad-8pro-mainline , release v0.6.0.

1. First git clone the repository and check out tag v0.6.0. Read README.md "Read Before Installing", docs/INSTALL.md, docs/FLASHING.md and the safety rules in section 1 of docs/AGENT-GUIDE.md before doing anything.
2. Download every asset of GitHub release v0.6.0 into one empty directory, run sha256sum -c SHA256SUMS.assets first, then restore the release directory as the release notes describe and verify it again.
3. Check the host tools (adb, fastboot, python3, zstd, sgdisk, sfdisk, img2simg and the rest of the "Prerequisites" table in INSTALL) and the tablet (product piano, stock build OS3.0.303.0.WPYCNXM, current slot a, unlocked, rooted, battery at least 40 %). If anything does not match, stop and tell me; do not work around it.
4. Follow docs/INSTALL.md strictly in order and explicitly select my tablet with -s or --serial in every device command. Before each step, tell me in a sentence or two what it does and where it writes. For every operation that writes to the tablet (partition table, erase, flash, slot A), list the exact commands and wait for me to reply "confirm" before running them.
5. Never write vbmeta, dtbo, any _b partition, persist or any other calibration, modem or firmware partition; never run fastboot --set-active=b; never use calibration, per-unit configuration or images from another tablet.
6. No write step before the backup is complete and its hashes verified. Keep the backup and my per-unit files outside the repository; never commit or upload them anywhere.
7. Stop on any error: if a command fails or its output differs from the documented "expect" line, stop and show me the full output. Do not retry write commands on your own and do not interrupt a write in progress.
8. I will stay next to the tablet. When I need to act on it (key combination for Fastboot, creating the account in Initial Setup, typing a password), tell me exactly what to do and what to wait for.
9. After the installation, finish the last step as documented (install the per-unit files, store the Android image set, rebuild the boot set, turn developer mode off), then explain how to switch between the two systems and how to recover Android from Fastboot.
```

### Manual installation

1. Download every asset of the [v0.6.0 release](https://github.com/yzddmr6/xiaomipad-8pro-mainline/releases/tag/v0.6.0) into one empty directory, verify it and restore the release directory:

   ```bash
   sha256sum -c SHA256SUMS.assets
   unzip piano-ubuntu-v0.6.0-boot.zip && unzip piano-ubuntu-v0.6.0-tools.zip && unzip piano-ubuntu-v0.6.0-packages.zip
   mkdir -p rootfs && cat piano-ubuntu-v0.6.0-rootfs.img.zst.part* | zstd -d > rootfs/root.sparse.img
   sha256sum -c SHA256SUMS
   ```

2. Follow [docs/INSTALL.md](docs/INSTALL.md) step by step. Switching, Fastboot recovery and the partitions that must never be written are in [docs/FLASHING.md](docs/FLASHING.md).

### Upgrading an existing installation

Follow [docs/UPGRADE.md](docs/UPGRADE.md) to upgrade the kernel and the device packages from the release's `packages.zip`; the upgrade keeps a rollback boot set.

### Building from source

The kernel, Mesa, the device packages, the root image and the signed boot set are all built on the host without root privileges, from inputs pinned in `kernel/source.json`, `mesa/source.json`, `ubuntu/` and `device/*/source.json`. See [docs/BUILD.md](docs/BUILD.md).

<a id="support-matrix"></a>

## Hardware Support

State of v0.6.0 on the test unit. ✅ works · 🟡 partial · ❌ unsupported · 🧪 untested.
✅ means the described function was verified on the tablet, not that every application and use case was tested. Current support and improvements by release are in [docs/STATUS.md](docs/STATUS.md).

### Platform, Display and Input

| Function | Hardware / implementation | Status | Notes |
|---|---|---|---|
| SoC / CPU | Qualcomm Snapdragon 8 Elite (SM8750P) | ✅ works | All eight cores with frequency scaling |
| Android / Linux dual boot | Slot-A image-set rotation | ✅ works | Switching from Ubuntu (one command), from Android (KernelSU module) and from the host (Fastboot) all verified |
| Internal storage | KIOXIA UFS / ext4 | ✅ works | 60 GiB root, about 201 GiB `/home` |
| Internal display | Native DSI KMS (`msm_dpu`) | ✅ works | 3200×2136; 60/90/120/144 Hz changes and screen off/on verified |
| Night Light | GNOME / DPU color temperature | ✅ works | Color temperature adjustment with settings preserved across screen off/on and suspend |
| GNOME desktop | Ubuntu 26.04 GNOME / Wayland / GDM | ✅ works | Cold boot to the login screen in about 13 s |
| GPU | Adreno 830 / Mesa 26.2 | ✅ works | GPU rendering for the desktop and for snap applications including Firefox |
| Touchscreen | Novatek NT36532E (THP over SPI) | 🟡 partial | Touch input at 60/90/120/144 Hz and after screen off/on and suspend; multi-finger gestures untested |
| Magnetic keyboard | Nanosic WN8030 | ✅ works | Typing, key wake with the screen off and wake from suspend |

Not yet supported: stylus, fingerprint.

### Wireless and USB

| Function | Hardware / implementation | Status | Notes |
|---|---|---|---|
| Wi-Fi | Qualcomm WCN7860 / ath12k | ✅ works | Stable 2.4 GHz and 5 GHz 80 MHz links |
| Bluetooth | Qualcomm WCN7860 / `hci_qca` | 🟡 partial | Pairing, file transfer and audio work; occasionally needs reconnecting |
| USB device mode | USB 3 / 5 Gbit/s networking (NCM) | ✅ works | SSH over the USB cable in developer mode, off by default |
| USB host / OTG | Type-C role switching / USB 3 / 5 Gbit/s | 🟡 partial | USB sticks, keyboards, mice and docks work at 5 Gbit/s in both orientations; a plain OTG adapter may not be detected when re-plugged right after an OTG device is removed |
| USB-C external display | DisplayPort Alt Mode | ✅ works | Both orientations and hot-plug; tested at 4K 60 Hz as an extended desktop |

### Audio, Video and Sensors

| Function | Hardware / implementation | Status | Notes |
|---|---|---|---|
| Speakers | FS19xx quad amplifiers | 🟡 partial | Playback works; maximum volume increased; no speaker protection |
| Internal microphones | DMIC / ADSP / PipeWire | ✅ works | Recording verified |
| Video decoding | Qualcomm Iris / V4L2 | ✅ works | Automatic hardware decoding in the system player (GStreamer), Firefox (H.264/HEVC/VP9) and Chrome (H.264/VP9); AV1 uses software decoding |
| Video encoding | Qualcomm Iris / V4L2 | ✅ works | H.264/H.265 at 1080p and 4K verified |
| Cameras | Rear S5KJN1SQ03, front OV32D40 | ✅ works | Front and rear cameras available in camera apps; fixed rear focus, suited to subjects beyond close range |
| Accelerometer, gyro, light, proximity | SSC / hexagonrpcd / libssc | ✅ works | SensorProxy reports orientation and ambient light |
| Auto-rotation | SensorProxy / Mutter | ✅ works | Rotates with the keyboard detached; locked by GNOME's rule while the keyboard is attached |

Some HEVC videos may drop a small number of frames in Firefox. Chromium snap is not covered by this acceleration integration.

### Power and Time

| Function | Hardware / implementation | Status | Notes |
|---|---|---|---|
| Power / volume keys | Qualcomm PMIC | 🟡 partial | Power key locks the screen by default and wakes the lock screen; action configurable in Settings → Power; volume keys unverified |
| Power modes | GNOME / TuneD | ✅ works | Power Saver, Balanced and Performance in quick settings or Settings → Power; Balanced by default |
| Battery gauge / temperature | 2 × TI BQ27Z561 / thermal zones | ✅ works | Charge level, voltage, current and temperatures |
| Charging | `xiaomi_mca` / SC8541 | 🟡 partial | Charging and charging restoration after suspend; limited charger compatibility |
| Suspend | suspend-to-idle | ✅ works | Timer, keyboard, power-button and cover-open wake; default system idle policy |

Not yet supported: disk hibernation, hardware clock writes (time is set from the network after boot).

## Usage and Maintenance

Host commands use the REPO, RELEASE and WORK variables from [INSTALL.md "What you need"](docs/INSTALL.md#what-you-need) and run in WORK. Details are in [docs/FLASHING.md](docs/FLASHING.md).

**Switching.** In Ubuntu, `sudo piano-boot-switch to-android --reboot` writes the stored Android image set to slot A, reads it back and reboots. In Android, the [KernelSU switch module](device/android/piano-switch-ksu/README.md) switches to Ubuntu. Switching from within either system does not change the slot attributes.

**Recovery from the host.** With the tablet in Fastboot (Power + Volume Down), `tools/piano-switch.py` checks the device and both image sets, writes slot A and restores the previous set if any write fails:

```bash
python3 "$REPO/tools/piano-switch.py" --serial <serial> --images <android-set> --rollback <ubuntu-set>
fastboot -s <serial> reboot
```

A host write resets slot A's retry counter; the next Ubuntu boot marks the slot successful again. If Fastboot reports `slot-unbootable:a` as `yes`, run `fastboot -s <serial> --set-active=a` to reset it; slot B stays unused.

**Developer mode.** `sudo piano-devmode on` enables SSH over the USB cable; it is off by default. Connect from the host with `python3 "$REPO/tools/piano-devmode-ssh.py" --serial <serial> <user>`, and turn it off afterwards with `sudo piano-devmode off`. See [device/devmode](device/devmode/README.md).

**Upgrades.** See [docs/UPGRADE.md](docs/UPGRADE.md). Installing a kernel package rebuilds the boot set and rewrites slot A; the previous set is kept for rollback.

**Time.** The hardware clock is not writable; the time is set from the network after boot. Without a network, set it with `sudo date -s 'YYYY-MM-DD HH:MM'`.

**Sensor calibration.** The image ships default calibration only. To use your own tablet's stock calibration, prepare it from your own backup as described in the [sensor instructions](device/sensors/README.zh-CN.md) (Chinese); never use another tablet's.

**After Initial Setup.** Initial Setup sets the hostname from its *Computer* field; change it later with `sudo hostnamectl hostname --static <name>`. Run `sudo apt update` before the first `apt install`: the image ships without package indexes.

**App Center.** Once online, run `sudo snap refresh snap-store gnome-46-2404` to update App Center.

## Development and Contributions

| Repository | Content |
|---|---|
| xiaomipad-8pro-mainline | Device userspace, Ubuntu integration, build/packaging/switching tools, firmware, documentation |
| [linux-sm8750-piano](https://github.com/yzddmr6/linux-sm8750-piano) | Linux kernel: drivers, devicetree and configuration maintained on top of upstream Linux 7.2 stable, release commit pinned in the input lock |

See [docs/BUILD.md](docs/BUILD.md) to build the kernel, Mesa, device packages and images; [kernel/source.json](kernel/source.json) pins the kernel commit and configuration fragments.

Before operating on a device, read [docs/AGENT-GUIDE.md](docs/AGENT-GUIDE.md), written for human operators and AI assistants; contribution rules are in [CONTRIBUTING.md](CONTRIBUTING.md).

Report problems through [GitHub Issues](https://github.com/yzddmr6/xiaomipad-8pro-mainline/issues) with the device model, stock build and project release; strip serial numbers, Bluetooth addresses, calibration data and personal information first.

## Acknowledgments and Licensing

This project reuses and adapts the following work:
- the OnePlus Pad 2 Pro (`erhai`) mainline integration project (GPL-2.0-only);
- the Xiaomi Pad 6 Pro (`liuqin`) mainline project: [integration](https://github.com/yzddmr6/xiaomipad-6pro-mainline) (MIT) and [kernel](https://github.com/yzddmr6/linux-sm8450-liuqin) (GPL-2.0);
- [BigfootACA/linux](https://github.com/BigfootACA/linux/tree/full-v7.1.3) (GPL-2.0);
- [ROCKNIX](https://github.com/ROCKNIX/distribution/tree/92a6fca6afda5ab7e1874af8985095beee19b6a8) and Teguh Sobirin's [SM8750 kernel patches](https://github.com/ROCKNIX/distribution/tree/92a6fca6afda5ab7e1874af8985095beee19b6a8/projects/ROCKNIX/devices/SM8750/patches/linux) (GPL-2.0; DTS BSD-3-Clause);
- Qualcomm (Jie Zhang, Akhil P Oommen, Gaurav Kohli): the [Adreno 830 series](https://patchew.org/linux/20260809-pakala-gpu-v1-0-207ad1fac1c7%40oss.qualcomm.com/) (GPL-2.0);
- Junjie Cao: the [NT36532 panel driver](https://patch.msgid.link/20260804074233.85629-1-junjie.cao@linux.dev) (GPL-2.0-only);
- Alexander Koskovich and Jonathan Marek: the [DSC slice-per-packet patch](https://patch.msgid.link/20260318-dsi-dsc-slice-per-pkt-v2-1-0a1b316f8250@pm.me) (GPL-2.0);
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

Related projects (studied, used as references):
- [Project-SunUEFI](https://github.com/slwyts/Project-SunUEFI) (per-file licences);
- [blu-sharky/linux-piano](https://github.com/blu-sharky/linux-piano) (GPL-2.0);
- [blu-sharky/debian-piano](https://github.com/blu-sharky/debian-piano) (MIT).

Per-file origins, commits and changes are recorded in [NOTICE](NOTICE). Unless a file's SPDX header says otherwise, original integration code is [MIT](LICENSE); a few tools adapted from GPL-2.0-only sources stay GPL-2.0-only. The kernel is GPL-2.0. Third-party components keep their own licences (see `LICENSES/`). The stock firmware in [firmware/](firmware/README.md) is taken from OS3.0.303.0.WPYCNXM and redistributed unchanged for interoperability. The vendors have not granted redistribution permission; these files are not covered by the licences above and will be removed at a rights holder's request. You can replace them with firmware extracted from your own device using the documented tools.
