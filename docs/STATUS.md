# Status

Current release: **v0.3.2**. The support matrix is in the [README](../README.md#hardware-support)
and the [中文 README](../README.zh-CN.md#硬件支持). This page records what was verified, the
remaining limitations and the upstreaming state.

## Included fixes since v0.2.0

The desktop Mesa package now fixes a shared-context creation race exposed by
Settings video previews. A real-device EGL/GLES reproducer crashed on the old
package and passed with the fix; hardware rendering remains enabled. The
published v0.2.0 images and snap graphics provider still contain the old build.

Bluetooth initialization now has a bounded MGMT helper using the unit address
already installed before first boot. This removes the dependency on rebuilding
a device-specific boot image before BlueZ can see an unconfigured controller.
It does not establish pairing, audio or wake support.
The generic-DTB path was tested on the tablet: the DT address property was
absent, the helper configured the controller, and BlueZ used the installed
unit address.

An open touchscreen stream now survives the device suspend/resume stage.
System suspend is now enabled after the charging, battery, keyboard and display
resume fixes passed tablet acceptance. GNOME hides the rotation toggle while the keyboard is
attached. The power-button action is configurable in Settings → Power, with suspend as the default; existing personal choices are preserved.

## Test unit and historical installation configuration

All results belong to the one tested unit. They do not establish support for other units,
variants or accessories.

| Item | Value |
|---|---|
| Device | Xiaomi Pad 8 Pro (`piano`), model 25091RP04C (China), SoC SM8750P, 16 GB RAM, 512 GB UFS; bootloader unlocked |
| Stock build | OS3.0.303.0.WPYCNXM on slot A |
| Kernel | Linux 7.2.10 with the piano patches; the exact commit and configuration are pinned in [kernel/source.json](../kernel/source.json) and recorded in the release notes |
| Userspace | Ubuntu 26.04 Desktop ARM64; Mesa 26.2 as a deb and as a snap `gpu-2404` provider; GStreamer good/bad plugins |
| Sensors | `piano-sensors` (hexagonrpcd) and `piano-iio-sensor-proxy` (libssc-backed SensorProxy) with the default calibration seed |
| Installation | Fresh installation of the v0.2.0 images following `docs/INSTALL.md`; the cold-boot acceptance ran on an account created for the test before the first boot |

## Historical v0.2.0 cold-boot acceptance

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
input resumes after the screen is turned back on. These are historical v0.2.0 measurements; current suspend acceptance is listed below.

## v0.3.0 verification scope

GNOME Night Light passed 50 on/off cycles with 101 stable encoder-CRC endpoints, plus DPMS and suspend restoration. The session helper uses the distribution sRGB profile without overriding an existing user choice.

The release incorporates tablet-tested dual-camera capture (fixed rear focus), H.264/H.265/VP9 slow-consumer decoding (150/150 each), 60/90/120/144 Hz display switching and DPMS, six RTC suspend/resume cycles, physical power/keyboard/cover-open wake, screen-off key wake and typing, and charging current-limit restoration. Cover closing does not wake the tablet.

Bluetooth pairing, file transfer and audio are available, with an intermittent data failure after reconnecting. Camera autofocus is disabled after the actuator failed to open; neither control readback nor driver presence is treated as lens movement.

## v0.3.1 verification scope

Linux 7.2.10-piano25 fixes a shared display-control reset while the panel was still scanning: 42 screen-off cycles produced zero interface underruns, with CRC-verified pictures on both halves. RAM boot on the installed root passed all six display modes, 120/144 Hz DPMS CRC checks, two s2idle cycles, audio after resume and both camera streams. Imported community fixes cover audio readiness, freezable sensor waiters and DSI PHY interface-clock runtime PM.

The camera service starts automatically for apps. The optional NEON BGRx conversion and Snapshot preview were verified on the tablet. The touch service restarts after a stream error; recovery by restarting was verified on the tablet. Tolerance of one recovered SPI read failure has compile and KUnit coverage only; that failure was not reproduced on hardware.

## v0.3.2 verification scope

The upstream Turnip gen8 texture line-offset fix removes NV12 diagonal stripes with GTK's default Vulkan renderer. Synthetic NV12, Settings and other GTK Vulkan windows passed on the tablet, and the snap graphics provider was refreshed. The camera publishes NV12 by default again; `PIANO_CAMERA_OUTPUT=bgrx` in `/etc/piano/camera.conf` retains the optional NEON conversion. Lead measurements during a rear-camera preview were about 4 % of one core for camerad and 17 % for Snapshot with NV12, versus 19 % and 32 % with BGRx. Linux 7.2.10-piano25 and the other components are unchanged. Final assembled release images have not been tablet-booted.

## Known issues and remaining work

- Touch can fail at 120/60 Hz; return to 144/90 Hz.
- Bluetooth can reconnect without working data; AV1 decoding can lose its first frame.
- Rear focus is fixed and color tuning remains limited.
- In rare cases audio and the camera can stop working at the same time; a reboot recovers (seen once, under investigation).
- Touch may need a second to recover after a rare touch-controller restart.
- Stylus, USB host, USB-C external display and fingerprint are unsupported.
- Keep the speaker gain cap: speaker protection is absent. Disk hibernation is disabled; the hardware clock remains unwritable.
- Sensor calibration ships as a default seed; per-unit calibration must never be shared.

See the [v0.3.2 release changes](../packaging/release/changes/v0.3.2.md) and [README support table](../README.md#hardware-support) for the user-facing scope.

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
