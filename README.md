# Ubuntu on Xiaomi Pad 8 Pro (piano)

[中文](README.zh-CN.md)

Mainline-based Linux 7.2.y and Ubuntu 26.04 LTS with GNOME for the Xiaomi Pad 8 Pro (codename
`piano`, Qualcomm SM8750P), installed alongside Android. Both systems boot from the active A slot;
switching writes the other system's `boot`, `init_boot` and `vendor_boot` images from Fastboot. This
repository is the integration layer: build and packaging tools, device userspace and Ubuntu
integration; the kernel is maintained in a separate repository. The project is intended for
developers and experienced users who can recover the tablet over Fastboot. In the first release the
installed system boots to GNOME with display, touch and GPU acceleration; Wi-Fi and battery charging
are not yet available.

## Support matrix

Status on the test unit described in [Requirements](#requirements), as of 2026-10-08. Test
configuration, known issues and roadmap: [docs/STATUS.md](docs/STATUS.md).

**Working**: functions as expected · **Partial**: functions with the listed limits ·
**Untested**: enabled, function not verified · **Not yet**: not enabled · **Unsupported**: outside
the project scope

| Component | Status | Notes |
|---|---|---|
| Boot (ABL, AVB) | Partial | ABL boots a v4 `boot`/`init_boot`/`vendor_boot` set from slot A. AVB footers are signed with the owner's key, which only an unlocked bootloader accepts; `vbmeta` is unchanged. The slot is not yet marked as successfully booted, so it becomes unbootable after about seven Ubuntu boots unless reset. |
| Display | Partial | 3200×2136 at 120 Hz through simpledrm on the bootloader framebuffer (firmware scanout). No native MDSS/DSI/panel driver: brightness stays at the bootloader level; no screen-off or wake. Intermittent whole-screen flicker has been observed with touch active. |
| GNOME desktop | Working | Ubuntu 26.04 GNOME on Wayland with GDM, GPU-composited, 200 % scaling. |
| GPU | Working | Adreno 830 (msm DRM) with OpenGL ES from Mesa 26.2.0 plus one patch, packaged as `piano-mesa`. Ubuntu's Mesa 26.0.3 does not support the A830. Vulkan, sustained load and GPU power management are untested. |
| Touchscreen | Partial | Novatek NT36532E over SPI with host-side processing (`piano-thp`, per-device calibration). Single-finger input and orientation are correct. Long press does not work; multi-touch, edge accuracy and power management are untested. |
| Stylus | Not yet | Pen scanning is disabled when touch starts. |
| Magnetic keyboard | Partial | Xiaomi keyboard through the Nanosic WN8030 I2C bridge (`hid-nanosic`); keys work. Detach/reattach and power management are untested. The tested keyboard has no touchpad. |
| Power key | Partial | Key events reach logind; screen-off and wake are unavailable. Volume keys are untested. |
| Bluetooth | Partial | WCN7860 over UART: firmware loading, power-on and device discovery. Pairing, audio and Wi-Fi coexistence are untested. |
| Wi-Fi | Not yet | WCN7860 on PCIe (ath12k). PCIe stays disabled until the PHY supply mapping of this board is established. |
| Speakers | Not yet | Four FS19xx-family amplifiers have no mainline driver; no playback device exists. |
| Microphone | Untested | Internal DMIC path through the ADSP (AudioReach): the sound card and capture PCM register, but the PCM reports no backend DAI. Recording is untested; no UCM profile. |
| Battery gauges, thermal | Working | Two BQ27Z561 gauges report capacity, voltage and current; thermal zones are readable. Thermal throttling is untested. |
| Charging | Not yet | No charger driver. The battery discharges under Linux, also with USB connected; charge in Android. |
| Suspend | Not yet | Disabled by policy (systemd `sleep.conf.d`, GNOME idle override) until suspend and resume are validated. |
| Hibernation | Unsupported | The layout has no swap partition. |
| Real-time clock | Not yet | The PMIC RTC cannot be written; the time is wrong after each boot until set manually. |
| Internal storage | Working | UFS; ext4 root (60 GiB) and `/home` (about 201 GiB). |
| USB device mode | Partial | USB 2.0 NCM gadget in debug images only; release images expose no USB function. |
| USB host, Type-C roles | Not yet | Type-C role switching (UCSI) is not enabled. |
| External display | Not yet | DisplayPort Alt Mode requires the native display driver; the DP and DIO4485 SBU-switch nodes are disabled. |
| Video decoding | Not yet | Iris (VPU35) is built as modules but not enabled. |
| Sensors | Not yet | Rotation, light and Hall sensors sit behind the ADSP sensor hub (SSC); the userspace stack is prepared but not enabled. |
| Cameras | Not yet | S5KJN1SQ03 rear and OV32D40 front sensors; mainline lacks SM8750 CAMSS support. |
| Fingerprint | Not yet | No driver. |

## Requirements

- **Device:** Xiaomi Pad 8 Pro (`piano`, SM8750P). The test unit is model 25091RP04C (China) with
  16 GB RAM and 512 GB UFS. Other variants and storage sizes are untested; the layout below assumes
  512 GB.
- **Stock build OS3.0.303.0.WPYCNXM.** The firmware locks in `firmware/` pin its file names and
  hashes. The boot images copy its header fields (OS version, security patch level), rollback
  indices and AVB properties; without them ABL marks the slot unbootable. The boot DTB is prepared
  against its stock DTB and DTBO, which ABL overlays at boot. On the test unit slot B holds an older
  stock chain that does not boot Android, so slot B is not a fallback.
- **Unlocked bootloader** (Xiaomi's official process); a locked bootloader is unsupported.
- **Backup** of every partition except `userdata`, plus the GPT of each UFS LUN, before any write;
  reading partitions requires root in Android. The stock `boot`, `init_boot` and `vendor_boot`
  images of slot A form the Android image set used for switching back.
- **Battery at 40 % or more** before leaving Android. Linux does not charge the battery.
- **Host:** Linux with `fastboot`, `adb` and Python 3 ([Build from source](#build-from-source)).

## What gets installed

| Partition (UFS LUN 0) | Size | Content |
|---|---|---|
| `userdata` | 200 GiB | Android data, re-created empty |
| `linux_rootfs` | 60 GiB | Ubuntu `/`, ext4 |
| `linux_data` | remainder, about 201.27 GiB | `/home`, ext4 |

- The three partitions occupy the original `userdata` range; other GPT entries and LUNs are
  unchanged. `userdata` and `metadata` are cleared and Android re-creates them: all Android data is
  lost.
- **Active-slot image rotation:** slot A holds either the Android or the Ubuntu image set; the other
  set is kept as checksummed files. `vbmeta`, `dtbo`, slot B and firmware partitions are never
  written.
- **Ubuntu image set:** `boot.img` (kernel, command line with the root PARTUUID), `init_boot.img`
  (empty ramdisk) and `vendor_boot.img` (distribution dracut initrd, boot DTB with the device's
  Bluetooth address), sized like the stock partitions (96, 8 and 96 MiB).
- **Image locations:** the host build directory holds the images, `SHA256SUMS` and
  `manifest.json`. On the installed system the kernel postinst hook `piano-boot-update` rebuilds the
  Ubuntu set in `/var/lib/piano/switch/ubuntu/` after kernel or initrd updates without writing
  partitions; the Android set is kept in `/var/lib/piano/switch/android/`.
- **Packages:** `linux-image-7.2.6-piano+`; `piano-device-support` (boot hooks, touch service,
  platform helper, suspend policy); `piano-local-firmware` (device firmware, local use only);
  `piano-mesa` and `piano-ubuntu-desktop` (Mesa environment, display scale).

## Installation

The partitioning and root-filesystem installer is not published yet ([roadmap](docs/STATUS.md#roadmap)).
The installation consists of these steps:

1. Back up the device as described in [Requirements](#requirements).
2. Build the kernel, packages, root filesystem and Ubuntu image set with the device's own inputs.
3. In a RAM-booted Linux environment (`fastboot boot`), identify the target by UFS controller, LUN,
   GPT GUIDs, labels and geometry: `sdX` names change between boots, and backup file names are not
   device names. Rewrite the LUN 0 GPT (backup GPT first), clear `userdata` and `metadata`, write the
   root filesystem, and create the empty `/home` filesystem on the device. A sparse image of an
   empty ext4 encodes zero blocks as FILL chunks, which the device still writes in full.
4. Write the Ubuntu image set to slot A with `tools/piano-switch.py`.

### Switching and recovery

`tools/piano-switch.py` runs on the host in Fastboot mode. It checks the product, unlock state,
current slot and partition sizes, verifies both image sets against their `SHA256SUMS`, writes
`init_boot_a`, `vendor_boot_a` and `boot_a` in that order, and writes the rollback set back if a
write fails. The three writes are not atomic; a power loss during a switch can require recovery
from the host.

```sh
# To Android: in Ubuntu, power off, then hold Power + Volume Down for Fastboot.
python3 tools/piano-switch.py --serial <serial> --images <android-set> --rollback <ubuntu-set>
fastboot -s <serial> reboot

# To Ubuntu, from Android:
adb -s <serial> reboot bootloader
python3 tools/piano-switch.py --serial <serial> --images <ubuntu-set> --rollback <android-set>
fastboot -s <serial> reboot
```

- **No picture or no response:** hold Power + Volume Down to enter Fastboot and switch to Android.
  Release images have no debug console.
- **Stuck in Fastboot with `slot-unbootable:a` = `yes`:** `fastboot -s <serial> --set-active=a`
  resets slot A's retry counter. On the test unit this also raised slot B's priority; slot B remains
  unusable.
- **Diagnostics without writing partitions:** a debug build (`build-persistent-boot.py --debug
  --debug-timeout <seconds>`) also produces `boot-ram-check.img` for `fastboot boot`. It starts the
  installed system with an unauthenticated root shell over USB NCM (192.168.88.2, port 2323) and
  returns to Fastboot when the timeout expires.
- Never flash `vbmeta`, write slot B or activate slot B. Android OTA updates are untested here.

## Build from source

| Input | Pin |
|---|---|
| Kernel | [`kernel/source.json`](kernel/source.json): commit on branch `piano/dev`, based on v7.2.6 |
| Kernel configuration | `piano-diagnostic.config` + `piano-desktop-diag.config` + `piano-persistent.config`, modules enabled; DTB `sm8750-xiaomi-piano-desktop.dtb` |
| Ubuntu | official 26.04 Desktop ARM64 ISO, SHA-256 `c2afd538d66fdd77377d03f1ed2ac76a34f1c116baecc9a8170d68f833121f57`; [`ubuntu/26.04.sources`](ubuntu/26.04.sources); APT inputs from snapshot.ubuntu.com timestamps |
| Mesa | [`mesa/source.json`](mesa/source.json) (26.2.0) and `mesa/a830-speedbin.patch` |
| AOSP tools, BusyBox | `tools/fetch-aosp-mkbootimg.sh` (pinned commit), `tools/fetch-busybox-arm64.sh` (Ubuntu package); `avbtool` from AOSP `external/avb` has no fetch script yet and is passed with `--avbtool` |
| Other userspace | `device/*/source.json`, `ubuntu/systemd/source.json` |

| Area | Tools in `tools/` |
|---|---|
| Kernel | `build-kernel.sh` (image, DTBs, modules, `build-result.json`); `build-kernel-deb.py` (`linux-image` package whose Ubuntu maintainer scripts run dracut) |
| Boot | `prepare-boot-dtb.py` (boot DTB with the stock overlay symbols ABL expects); `build-persistent-boot.py` (signed v4 set and v2 RAM check image); `piano-switch.py` (switch with rollback) |
| Ubuntu root | `prepare-ubuntu-desktop.sh`, `merge-desktop-tars.py`, `prepare-ubuntu-apt.py`, `build-ubuntu-ext4.py` (official layers, signed APT inputs, ext4 image, all without root privileges) |
| Userspace | `build-mesa.sh`; `extract-thp-calibration.py`; `build-firmware-deb.py`, `stage-firmware.py` (DSP firmware); `build-device-debs.py` (the four `piano-*` packages) |
| Diagnostics | `build-boot.py`, `build-initramfs.sh`, `prepare-module-initramfs.py` (bounded RAM images) |

```sh
CONFIG_FRAGMENT_EXTRA="arch/arm64/configs/piano-desktop-diag.config arch/arm64/configs/piano-persistent.config" \
BUILD_MODULES=1 KERNEL_SOURCE=/path/to/linux OUT_DIR="$PWD/out/kernel-persistent" bash tools/build-kernel.sh

python3 tools/build-persistent-boot.py --kernel <Image> --dtb <boot.dtb> --initrd <initrd> \
  --profile <boot-profile.json> --mkbootimg tools/local/aosp-mkbootimg/mkbootimg.py \
  --avbtool <avbtool.py> --key <signing-key.pem> --root-partuuid <linux_rootfs PARTUUID> \
  --bt-address-file <bluetooth-address> --output out/ubuntu-boot
```

Detailed build notes (Chinese, including RAM diagnostics): [docs/build.zh-CN.md](docs/build.zh-CN.md).

**Device-specific inputs** come from the owner's device and are never committed (`.gitignore`
excludes their usual names):

- **Firmware** from the same stock build: ADSP/CDSP (`adsp*`, `cdsp*`; lock
  `firmware/piano-os3.0.303.0.json`), GPU (`gen80000_sqe.fw`, `gen80000_gmu.bin`,
  `gen80000_aqe.fw`, device-signed `gen80000_zap.mbn`; lock `firmware/piano-gpu.json`), Bluetooth
  (`gngbtfw20.mbn`, `gngbtnv20.*`; lock `firmware/piano-bluetooth-rom20.json`), touch
  (`novatek_nt36532_piano_fw_csot.bin`) and keyboard bridge (`MCU_Upgrade.bin`). Redistribution
  rights are not established; generated firmware packages stay local.
- **Touch calibration**, extracted from the stock `piano_nova_csot_thp_config.ini`.
- **Bluetooth address** of the device; without it the controller keeps its NVM default and stays
  unconfigured.
- **Boot profile:** stock header geometry, capacities, rollback indices and AVB properties of
  `boot`, `init_boot` and `vendor_boot`, and the observed active slot. The generator is part of the
  unpublished installer.
- **Stock DTB and DTBO** for `prepare-boot-dtb.py`; an owner-generated **AVB signing key** (RSA-4096).

**Reproducibility:** the kernel package is byte-identical for identical inputs. `init_boot.img`
depends on the Python version (the gzip header of its empty ramdisk records OS byte 0x03 under
Python 3.12 and 0xff under 3.14; both are functionally identical). dracut initrds are not
reproducible, so `vendor_boot.img` differs between builds. `CONFIG_MODVERSIONS` is disabled: install
the kernel image and modules from the same build.

## Repository layout

```
device/      device userspace: boot integration, touch processing (piano-thp), platform identity
             helper, audio topology, QRTR and sensor stacks
docs/        status page and build notes
firmware/    identity locks (names, sizes, SHA-256) for user-supplied firmware; no firmware bytes
initramfs/   RAM diagnostic initramfs: USB NCM console, Ubuntu RAM root, module delivery
kernel/      source.json: kernel repository pin
mesa/        Mesa source lock, A830 patch and device checks
packaging/   files installed by piano-device-support
tools/       build, packaging and switching tools
ubuntu/      APT sources and the systemd source-package override
LICENSES/    third-party licence texts
```

Three repositories have separate responsibilities: **integration** (this repository: tools, device
userspace, Ubuntu integration, input locks, documentation); **kernel** (`linux-sm8750-piano`, branch
`piano/dev`: drivers, device trees, bindings and configuration on the upstream stable history;
`kernel/source.json` pins the commit and records the public location once published); and
**device-specific inputs** (firmware, calibration, Bluetooth address, boot profile, signing key,
backups), which belong to each device owner and are never committed to either repository.

## Roadmap and upstreaming

Known issues, roadmap and upstreaming state: [docs/STATUS.md](docs/STATUS.md). No patch has been
submitted upstream yet; candidates include driver core, Adreno power-voting, simpledrm, DIO4485
Type-C, PMIC GLINK Alt Mode and Qualcomm ASoC fixes, and the NT36532E touch and Nanosic drivers.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Hardware reports state the device
model, stock build, kernel commit and image set identity, and omit serial numbers, Bluetooth
addresses, calibration data and personal information. The issue tracker and public remote are not
established yet.

## Credits and licence

This project reuses and adapts work from:
- the OnePlus Pad 2 Pro (`erhai`, SM8750P) mainline integration project: boot image, initramfs, RAM
  root and desktop layer tools (GPL-2.0-only; no public URL yet);
- the Xiaomi Pad 6 Pro (`liuqin`) mainline project: AOSP and BusyBox fetch scripts, Desktop layer
  preparation, iio-sensor-proxy patches and the HID transport of `hid-nanosic` (MIT);
- ROCKNIX and Teguh Sobirin: WCN7860 Wi-Fi, Bluetooth and power-sequencing commits, SM8750 GPU clock
  nodes and the Mesa A830 chip-ID reference;
- Qualcomm (Jie Zhang, Akhil P Oommen, Gaurav Kohli): Adreno 830 support; Junjie Cao: NT36532 panel
  driver; Alexander Koskovich and Jonathan Marek: DSC support;
- Novatek touch sources: Xiaomi's `vendor_xiaomi_proprietary_touch-driver` (GPL-2.0, Novatek) for
  the kernel THP transport, and ianchb's `xiaomi-sheng-thp` (Apache-2.0) for finger processing in
  `piano-thp`; map220v: WN8030 keyboard firmware encoding;
- AOSP `mkbootimg` (Apache-2.0) and `avbtool` (MIT); Mesa (MIT); linux-msm `hexagonrpc` and `qrtr`;
  libssc; iio-sensor-proxy; AudioReach topology; TinyALSA; systemd; BusyBox; Ubuntu.

Per-file sources, commits and changes are recorded in [NOTICE](NOTICE). Original integration code is
licensed under [MIT](LICENSE) unless a file's SPDX header states otherwise; several tools adapted
from GPL-2.0-only sources remain GPL-2.0-only. The kernel is GPL-2.0. Third-party components keep
their licences (see `LICENSES/`). Firmware belongs to its respective owners, is not distributed and
is not covered by these licences.
