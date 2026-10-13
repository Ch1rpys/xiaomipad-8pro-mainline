# Status

Current release: **v0.2.0**. The support matrix is in the [README](../README.md#support-matrix)
and the [中文 README](../README.zh-CN.md#硬件支持). This page records what was verified, the
remaining limitations and the upstreaming state.

## Development fixes after v0.2.0

The desktop Mesa package now fixes a shared-context creation race exposed by
Settings video previews. A real-device EGL/GLES reproducer crashed on the old
package and passed with the fix; hardware rendering remains enabled. The
published v0.2.0 images and snap graphics provider still contain the old build.

Bluetooth initialization now has a bounded MGMT helper using the unit address
already installed before first boot. This removes the dependency on rebuilding
a device-specific boot image before BlueZ can see an unconfigured controller.
It does not establish pairing, audio or wake support.

## Test configuration

All results belong to the one tested unit. They do not establish support for other units,
variants or accessories.

| Item | Value |
|---|---|
| Device | Xiaomi Pad 8 Pro (`piano`), model 25091RP04C (China), SoC SM8750P, 16 GB RAM, 512 GB UFS; bootloader unlocked |
| Stock build | OS3.0.303.0.WPYCNXM on slot A |
| Kernel | Linux 7.2.6 with the piano patches; the exact commit and configuration are pinned in [kernel/source.json](../kernel/source.json) and recorded in the release notes |
| Userspace | Ubuntu 26.04 Desktop ARM64; Mesa 26.2 as a deb and as a snap `gpu-2404` provider; GStreamer good/bad plugins |
| Sensors | `piano-sensors` (hexagonrpcd) and `piano-iio-sensor-proxy` (libssc-backed SensorProxy) with the default calibration seed |
| Installation | Fresh installation of the v0.2.0 images following `docs/INSTALL.md`; the cold-boot acceptance ran on an account created for the test before the first boot |

## Cold-boot acceptance

[tools/piano-cold-boot-accept.py](../tools/piano-cold-boot-accept.py) checks a cold boot of the
installed system against fixed budgets. The v0.2.0 fresh installation passed:

| Check | Budget | Result |
|---|---|---|
| First light (firmware framebuffer) | < 1 s | 0.16 s |
| Switch to the root filesystem | ≤ 10 s | 5.9 s |
| GDM login screen | ≤ 20 s | 12.3 s |
| GPU firmware (GMU) loaded | ≤ 20 s | 0.7 s |
| Native scanout | dual INTF at 144 Hz | pass |
| Clock / DSI / GPU errors over 200 s | 0 | 0 |
| Failed systemd units | 0 | 0 |

The firmware framebuffer is only the initial display path; native DSI KMS (`msm_dpu`) drives
3200×2136 at 144 Hz. Backlight control and screen off/on through Mutter are verified, and touch
input resumes after the screen is turned back on. This is not
suspend/resume acceptance: suspend is disabled.

## Verification scope

| Area | Verified result and limit |
|---|---|
| Dual boot | Slot-A image-set rotation from Ubuntu (`piano-boot-switch`), from Android (KernelSU module) and from the host (`piano-switch.py`); clean shutdown before switching |
| GPU | Adreno 830 with Mesa 26.2; GNOME Shell and Firefox (snap, through the `gpu-2404` provider) render on the GPU |
| Video | Iris V4L2 decoder: 150 of 150 frames of a 1080p H.264 clip bit-exact against software decoding; encoder node present but untested; automatic hardware decoding by players unverified |
| Wi-Fi | WCN7860 with ath12k: stable 2.4 GHz and 5 GHz 80 MHz links with Internet access and NTP |
| Bluetooth | Controller up with the unit's address, scanning finds devices; pairing and audio unverified |
| Speakers | FS19xx playback through PipeWire, gain capped; no speaker protection |
| Microphones | PipeWire capture of a 1 kHz tone 29–36 dB above the noise floor |
| Touch | NT36532E THP input and orientation confirmed by the user; the stream restarts after the panel is powered off and on; multi-finger gestures not tested systematically |
| Keyboard | WN8030 keys confirmed by the user; the accessory has no touchpad and no backlight |
| Sensors | Accelerometer, gyro, light and proximity samples through hexagonrpcd and libssc; SensorProxy reports orientation and ambient light; GNOME rotates with the keyboard detached (confirmed by the user) |
| Charging | Read-only charger and battery reporting; no charging control, net charging unverified |

## Known issues

1. **Charging is unverified.** Charger state is reported; charging control and net charging are
   not verified. Charge in Android and keep at least 40 % before switching.
2. **No speaker protection.** Playback keeps a fixed gain cap.
3. **Bluetooth is scan-only.** Pairing and Bluetooth audio are unverified.
4. **Video acceptance is limited** to a command-line decode; players may not pick the hardware
   decoder automatically, and the encoder is untested.
5. **Suspend is disabled** and **the RTC cannot be written**; the time comes from the network.
6. **Unsupported hardware:** cameras (no SM8750 camera subsystem), USB host and Type-C role
   switching, USB-C DisplayPort, stylus, fingerprint.
7. **Sensor calibration** ships as a default seed; the owner's stock calibration can be staged
   from a backup but is per unit and must never be shared.

## Roadmap

Charging control (wall-charger test), Bluetooth pairing and audio, application-level video
playback and encoding, speaker protection, suspend, RTC, cameras, USB host and external display
remain open. Installer automation is planned for a later release.

## Upstreaming

No patch from this project has been submitted upstream yet. Project-authored kernel commits are
drafts without `Signed-off-by` or `Fixes:` tags. Submission requires review and sign-off by a
human contributor, `Fixes:` tags against the full upstream history, and separate dt-bindings patches.

Upstream candidates in the kernel repository, by commit subject:

| Area | Commits |
|---|---|
| Driver core | driver core: release the old glue directory after a successful move; driver core: add KUnit coverage for device_move glue references |
| GPU power | pmdomain: qcom: rpmhpd: skip the retention level for GMXC |
| Firmware framebuffer | drm/simpledrm: describe firmware scanout bandwidth with an OPP table (the binding change is to be split out) |
| Type-C | dt-bindings: usb: fsa4480: describe DIO4485 compatible; usb: typec: fsa4480: support DIO4485 and propagate I/O failures; soc: qcom: pmic_glink_altmode: encode DP assignments and honor route failures |
| Audio | ASoC: qcom: sdw: avoid orphan streams on direct DMIC links; ASoC: lpass-tx-macro: use the channel mask for mixer state and mute (with its regression tests) |
| Pin control | pinctrl: qcom: sm8750: describe the TLMM I2C pull-up bit |
| Backlight | backlight: ktz8866: report register errors and support distinct instances; dt-bindings: leds: backlight: kinetic,ktz8866: describe a secondary chip; backlight: ktz8866: drive a secondary chip and keep the boot state |
| New drivers | Input: add NT36532E cascade THP transport and firmware tests; Input: nt36532e-thp: follow the shared TDDI panel power sequence; HID: nanosic: add initial piano I2C and HID transport; HID: nanosic: report tablet mode from the keyboard attach state. They lack power management |
| WCN7860 | wifi: ath12k: use a random MAC address if none is available; dt-bindings: regulator: qcom,qca6390-pmu: document the WCN7860 PMU; dt-bindings: net: bluetooth: add the Qualcomm WCN7860 binding; wifi: ath12k: declare WCN7860 firmware files; dt-bindings: net: wireless: qcom,ath12k: allow a MAC address property; wifi: ath12k: retrieve MAC address from system firmware if needed. These depend on the imported WCN7860 series |
| Charger | power: supply: qcom_battmgr: release the GLINK client after its users; soc: qcom: pmic_glink: add a client for the Xiaomi MCA charger firmware; power: supply: add a read-only driver for the Xiaomi MCA charger firmware (with KUnit tests); power: supply: xiaomi_mca: allow setting the input and charge currents (not yet exercised on the tablet); dt-bindings: soc: qcom: pmic-glink: document the Xiaomi Pad 8 Pro |
| Board | the `arm64: dts: qcom: piano:` series (board DTS) |

Local-only changes: soc: qcom: restore the DT root identity replaced by ABL, and the
configuration fragments. Diagnostic DT variants live on the kernel `piano/diag` branch, not on
`piano/dev`.

Imported community work keeps its original authorship, and its upstream status follows its
authors: the Adreno 830 driver, bindings, DT nodes, cooling and the RPMH dependency vote fix
(Jie Zhang, Akhil P Oommen, Gaurav Kohli; Qualcomm) and the SM8750 GPU clock and SMMU nodes
(Konrad Dybcio), all from linux-next; the q6v5 handover fixes (Abel Vesa, Shawn Guo; upstream);
the ath12k scan guard during firmware recovery (Jose Ignacio Tornos Martinez, FROMLIST); WCN7860
ath12k, PCI power control, power sequencing and Bluetooth (Teguh Sobirin); ath12k QDSS
configuration download (Gianni Spadoni); the PCIe `#iommu-cells` fix of
`qcom_pcie_config_sid_1_9_0()` (Manivannan Sadhasivam, linux-next); the ath12k frequency range
fix for single-pdev devices (Shenghan Gao, FROMLIST); APR/GPR and UFS fixes and the CPU thermal
trips (Junhao Xie, via BigfootACA/linux); the Novatek NT36532 panel driver (Junjie Cao); and DSC
slice-per-packet support (Alexander Koskovich, Jonathan Marek).
