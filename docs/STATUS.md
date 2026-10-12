# Status

Last updated: **2026-10-12**. The current kernel/package release is
**7.2.6-piano9 (ABI 9)**, installed and cold-boot accepted on piano.
The component support matrix is in the [README](../README.md#support-matrix)
and [中文 README](../README.zh-CN.md#硬件支持). This page records the
verification scope, remaining limitations and upstreaming state.

## Test configuration

These results belong to the tested piano. They do not establish support for
other units, variants or accessories. Earlier input checks and the separate
piano8-module video test are identified below.

| Item | Value |
|---|---|
| Device | Xiaomi Pad 8 Pro (`piano`), model 25091RP04C (China), SoC SM8750P, 16 GB RAM, 512 GB UFS; bootloader unlocked |
| Stock build | OS3.0.303.0.WPYCNXM |
| Kernel | `7.2.6-piano9` (ABI 9), commit `3ef018a0e9d5ac6e9a1b22ae85dd8e7b5c243166`; source/configuration identity in [kernel/source.json](../kernel/source.json) and [kernel/abi.json](../kernel/abi.json) |
| Installation | Updated from piano8 with an independent `piano9-rollback` image set retained; [upgrade procedure](PIANO9.md) |
| Userspace | Ubuntu 26.04 Desktop ARM64; Mesa 26.2 deb plus snap `gpu-2404` provider integration .3 |
| Desktop dependencies | GStreamer good/bad plugins are dependencies of `piano-ubuntu-desktop`; installation of plugins is not application playback verification |
| Sensor packages | `piano-sensors` (hexagonrpcd) and `piano-iio-sensor-proxy` (libssc-backed SensorProxy); private registry calibration staged from the owner's own backup |

## Cold-boot acceptance

[tools/piano-cold-boot-accept.py](../tools/piano-cold-boot-accept.py) accepted
the installed piano9 cold boot on 2026-10-12:

| Check | Device result |
|---|---|
| simpledrm first light | 0.18 s |
| switch_root | 6.0 s |
| GDM | 12.7 s |
| GMU | 0.87 s |
| Native scanout | Dual INTF at 144 Hz |
| Clock / DSI / GPU errors | Zero over 200 s |

simpledrm is only the initial display path; native DSI KMS (`msm_dpu`) drives
3200×2136 at 144 Hz. Backlight control through Mutter and DPMS off/on were
hardware-verified. This is not suspend/resume acceptance.

## Device verification scope

| Area | Verified result and limit |
|---|---|
| GPU | Adreno 830 with Mesa 26.2 deb and snap `gpu-2404` provider integration .3; Firefox WebRender verified |
| Video | Iris V4L2 decoder/encoder nodes present; 1080p H.264 hardware decode was bit-exact against software in a RAM check with piano8 modules; persistent piano9 exposes `/dev/video0/1`; application playback unverified and encoder untested |
| Wi-Fi | WCN7860 ath12k: stable 2.4 GHz and 5 GHz 80 MHz HE links verified on the installed kernel |
| Bluetooth | Scan found 4 devices; pairing and audio unverified |
| Speakers | FS19xx playback verified without speaker protection, with a −15 dB cap (TD-026) |
| Internal microphones | PipeWire capture verified: 1 kHz tone 29–36 dB above the noise floor |
| Touch | NT36532E THP input verified; orientation confirmed earlier by the user |
| Keyboard | WN8030 transport; keys confirmed earlier by the user; this keyboard has no touchpad |
| Sensors | SSC through hexagonrpcd and libssc: accelerometer, gyro, light and proximity samples verified; SensorProxy reports orientation |
| Rotation | Mutter's tablet-mode rule enables GNOME auto-rotation only with the keyboard detached; physical four-orientation test pending |
| Dual boot | Slot-A image-set rotation with `piano-boot-switch` and Android KernelSU module switching verified; clean shutdown on RAM-check return fixed |

## Known issues

1. **Charging is not accepted.** Read-only `xiaomi_mca` reporting is available;
   MiPPS/charging3 control awaits a wall-charger test. Net charging has not
   been verified. Charge in Android and keep at least 40 % before switching.
2. **Speaker protection is absent.** Verified FS19xx playback retains the
   −15 dB cap. Playback success does not close TD-026.
3. **Sensor calibration and rotation.** Stage private registry calibration
   from your own backup using
   [tools/stage-sensor-registry.py](../tools/stage-sensor-registry.py) and the
   [sensor package instructions](../device/sensors/README.zh-CN.md#原厂配置与私有标定).
   Never share or substitute another tablet's calibration. Samples and
   SensorProxy orientation do not establish physical four-orientation
   behavior; that test remains pending with the keyboard detached.
4. **Video acceptance is limited.** The bit-exact H.264 result belongs to the
   piano8-module RAM check. The installed piano9 root exposes both nodes;
   application-level playback and encoding have not been verified.
5. **Bluetooth acceptance is limited to scanning.** Pairing and audio remain
   unverified.
6. **Suspend is disabled** by product policy (D3). **The RTC cannot be set**
   (TD-022). Display DPMS off/on does not establish either capability.
7. **Unsupported hardware.** Cameras lack SM8750 CAMSS support; stock
   read-only evidence has been captured. USB-C DisplayPort external display
   has only offline control-chain evidence and is not supported yet. Stylus
   and fingerprint are unsupported.

## Roadmap

Remaining validation includes the wall-charger MiPPS/charging3 test, physical
four-orientation testing with the keyboard detached, Bluetooth pairing/audio,
application-level video playback and encoder testing. Speaker protection
(TD-026), suspend (D3), RTC setting (TD-022), cameras, external DisplayPort,
stylus and fingerprint remain open; the completed piano9 cold-boot checks do
not close these gaps.

## Upstreaming

No patch from this project has been submitted upstream yet. Project-authored
kernel commits are AI-generated drafts without `Signed-off-by` or `Fixes:`
tags. Submission requires review and sign-off by a human contributor, `Fixes:`
tags against the full upstream history, and separate dt-bindings patches.

Upstream candidates in the kernel repository, by commit subject:

| Area | Commits |
|---|---|
| Driver core | driver core: release the old glue directory after a successful move; driver core: add KUnit coverage for device_move glue references |
| GPU power | pmdomain: qcom: rpmhpd: skip the retention level for GMXC (the MX vote change was replaced by the upstream "drm/msm/a6xx: Fix RPMH dependency votes" in 7.2.6-piano5) |
| Firmware framebuffer | drm/simpledrm: describe firmware scanout bandwidth with an OPP table (the binding change is to be split out) |
| Type-C | dt-bindings: usb: fsa4480: describe DIO4485 compatible; usb: typec: fsa4480: support DIO4485 and propagate I/O failures; soc: qcom: pmic_glink_altmode: encode DP assignments and honor route failures |
| Audio | ASoC: qcom: sdw: avoid orphan streams on direct DMIC links; ASoC: lpass-tx-macro: use the channel mask for mixer state and mute (with its regression tests) |
| Pin control | pinctrl: qcom: sm8750: describe the TLMM I2C pull-up bit |
| Backlight | backlight: ktz8866: report register errors and support distinct instances; dt-bindings: leds: backlight: kinetic,ktz8866: describe a secondary chip; backlight: ktz8866: drive a secondary chip and keep the boot state |
| New drivers | Input: add NT36532E cascade THP transport and firmware tests; HID: nanosic: add initial piano I2C and HID transport; HID: nanosic: report tablet mode from the keyboard attach state. They lack power management |
| WCN7860 | wifi: ath12k: use a random MAC address if none is available; dt-bindings: regulator: qcom,qca6390-pmu: document the WCN7860 PMU; dt-bindings: net: bluetooth: add the Qualcomm WCN7860 binding; wifi: ath12k: declare WCN7860 firmware files; dt-bindings: net: wireless: qcom,ath12k: allow a MAC address property; wifi: ath12k: retrieve MAC address from system firmware if needed. These depend on the imported WCN7860 series |
| Charger | power: supply: qcom_battmgr: release the GLINK client after its users; soc: qcom: pmic_glink: add a client for the Xiaomi MCA charger firmware; power: supply: add a read-only driver for the Xiaomi MCA charger firmware (with KUnit tests); power: supply: xiaomi_mca: allow setting the input and charge currents (not yet exercised on the tablet); dt-bindings: soc: qcom: pmic-glink: document the Xiaomi Pad 8 Pro |
| Board | the `arm64: dts: qcom: piano:` series (board DTS) |

Local-only changes: soc: qcom: restore the DT root identity replaced by ABL
and the configuration fragments. The supervised diagnostic DT variants are
kept on the kernel `piano/diag` branch, not on `piano/dev`.

Imported community work keeps its original authorship; its upstream status
follows its authors: Adreno 830 driver, bindings, DT nodes, cooling and the
RPMH dependency vote fix (Jie Zhang, Akhil P Oommen, Gaurav Kohli; Qualcomm)
and SM8750 GPU clock and SMMU nodes (Konrad Dybcio), all taken from
linux-next since 7.2.6-piano5; the q6v5 handover fixes (Abel Vesa, Shawn
Guo; upstream); the ath12k scan guard during firmware recovery (Jose Ignacio
Tornos Martinez, FROMLIST); WCN7860 ath12k, PCI power control, power sequencing and
Bluetooth (Teguh Sobirin), ath12k QDSS configuration download (Gianni
Spadoni), the PCIe `#iommu-cells` fix of `qcom_pcie_config_sid_1_9_0()`
(Manivannan Sadhasivam, now from linux-next), the ath12k frequency range fix for
single-pdev devices (Shenghan Gao, FROMLIST), APR/GPR and UFS fixes and the
CPU thermal trips (Junhao Xie, via BigfootACA/linux), Novatek NT36532 panel driver (Junjie Cao),
and DSC slice-per-packet support (Alexander Koskovich, Jonathan Marek).
