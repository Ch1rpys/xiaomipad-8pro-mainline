# Status

Last updated: 2026-10-09. The component support matrix is in the
[README](../README.md#support-matrix). This page records the test
configuration, known issues, roadmap and upstreaming state.

## Test configuration

All hardware statuses refer to this configuration only.

| Item | Value |
|---|---|
| Device | Xiaomi Pad 8 Pro (`piano`), model 25091RP04C (China), SoC SM8750P, 16 GB RAM, 512 GB UFS; bootloader unlocked |
| Stock build | OS3.0.303.0.WPYCNXM |
| Kernel | `7.2.6-piano3` (ABI 3), kernel repository commit `e81699cfa` as pinned in [`kernel/source.json`](../kernel/source.json) and recorded in [`kernel/abi.json`](../kernel/abi.json); fragments `piano-diagnostic.config`, `piano-desktop-diag.config`, `piano-persistent.config`, `piano-release.config`; DTB `sm8750-xiaomi-piano-desktop.dtb`; 1071 modules. `7.2.6-piano2` stays installed and owns the rollback image set |
| Integration | this repository at `c9895bd`; `piano-device-support` 0.1+20261009.1, `piano-local-firmware` 0.2+os3.0.303.0 (built from `firmware/`) |
| Userspace | Ubuntu 26.04 Desktop ARM64; Mesa 26.2.0 with `mesa/a830-speedbin.patch` |

Verification basis: the installed system was checked with a debug image set
that is identical to the release set except for the kernel command line (it
adds a USB console and a session timeout). Display output was confirmed both
visually and with DPU frame counters. The release image set boots from slot A.

## Known issues

1. **Slot retry count.** ABL decrements slot A's retry counter on every boot
   of an unsuccessful slot. `piano-slot-success.service` marks slot A
   successful after a completed Ubuntu boot, and switching with
   `piano-boot-switch` keeps the attributes; a host `fastboot flash` resets the
   counter to 7 and clears the successful bit until the next Ubuntu boot.
2. **No charging.** The battery discharges under Linux, including with USB
   connected. The read-only `xiaomi_mca` client reports the USB input
   (`xiaomi-mca-usb`), but there is no charge control. Charge in Android and
   keep at least 40 % before switching to Linux.
3. **Clock.** The PMIC RTC cannot be written and there is no network time
   source; the time must be set manually after each boot.
4. **Display.** Firmware scanout only: brightness stays at the bootloader
   level and there is no screen-off or wake. simpledrm reports no physical
   size, so GNOME shows an unknown 40-inch monitor; `piano-ubuntu-desktop`
   presets 200 % scaling. Intermittent whole-screen black flicker has been
   observed with touch active; the cause is not identified.
5. **Touch.** Long press does not work: a stationary finger is released after
   about one frame. After the first touch the controller stays in 120 Hz
   active scanning. On the lock screen the GNOME on-screen keyboard fails and
   touch input is lost; enter passwords with the magnetic keyboard.
6. **Suspend disabled.** `piano-device-support` installs
   `/usr/lib/systemd/sleep.conf.d/50-piano-first-release.conf` (all sleep
   states refused) and a GSettings override that sets the GNOME idle actions
   to `nothing`. A same-named file in `/etc/systemd/sleep.conf.d/` re-enables
   sleep for testing; resume has never been exercised on this kernel.
7. **Kernel updates.** Installing `linux-image-7.2.6-piano3` took 22 s on the
   device (dracut, the kdump-tools initrd and the boot image set). The 10 to
   12.5 minutes measured before came from sessions running the older
   `7.2.6-piano+` kernel, with dispcc as a module and so probably in the slow
   display-clock state (memory bandwidth was not measured there). `piano-boot-update` then rebuilds
   the Ubuntu image set in `/var/lib/piano/switch/ubuntu/` and, on a
   persistent boot whose slot A holds an Ubuntu set, rewrites slot A in place.
8. **Generic kernels.** Kernel packages inherited from the Desktop image
   (`linux-image-7.0.0-14-generic`, `linux-generic-hwe-26.04`) remain
   installable and receive initrds, but cannot boot piano.
9. **Boot log errors without observed effect:** systemd `bpf-restrict-fs`
   fails to load; Bluetooth frame reassembly errors (-84) during firmware
   download; two snap user services fail. The UFS `EE_CONTROL` -22, the ADSP
   "Handover signaled" message, the qcom-apm command timeout and the deferred
   trace NOC are gone in 7.2.6-piano3.
10. **Debug entry.** `piano-debug.service` and `piano-debug-timeout.service`
    are installed and enabled but run only when the kernel command line
    contains `piano.debug=1`; that mode provides an unauthenticated root
    shell over USB. Release images do not set it.
11. **Module ABI.** `CONFIG_MODVERSIONS` is disabled. Install the kernel image
    and modules from the same build only.
12. **Package notices.** Locally generated packages contain third-party
    binaries (BusyBox, AOSP tools, Mesa) but no
    `/usr/share/doc/<package>/copyright` files yet. Keep them local.
13. **Wi-Fi.** The WCN7860 probes from the installed firmware, takes this
    unit's MAC address from the boot DTB (`/etc/piano/wlan-address`, see
    [device/boot](../device/boot/README.md)) and scans, but association, DHCP
    and throughput are untested; scans have found no 5 GHz network so far, and
    the board file is the API 1 `board.bin` (no `board-2.bin` yet).

## Roadmap

In priority order:

1. Wi-Fi: association and data on a user network, the missing 5 GHz scan
   results and a `board-2.bin` for each board SKU.
2. Charging: charge control over the vendor charger protocol (MCA), which
   differs from the upstream `battmgr` interface; reading it is done.
3. Publish the installer (partitioning, filesystem creation, boot-profile
   generation); add package copyright files, an avbtool fetch script and
   Python-independent `init_boot` output.
4. Native display: MDSS/DPU/DSI with the NT36532 panel driver and both
   KTZ8866 backlight controllers, providing brightness and screen-off/wake.
   External display depends on this step.
5. Suspend and resume (s2idle and deep) with display, touch, keyboard,
   Bluetooth and UFS recovery.
6. Speaker playback, microphone recording and UCM, USB host and Type-C
   roles, sensors, video decoding, cameras.

## Upstreaming

No patch from this project has been submitted upstream yet. Project-authored
kernel commits are AI-generated drafts without `Signed-off-by` or `Fixes:`
tags. Submission requires review and sign-off by a human contributor, `Fixes:`
tags against the full upstream history, and separate dt-bindings patches.

Upstream candidates in the kernel repository, by commit subject:

| Area | Commits |
|---|---|
| Driver core | driver core: release the old glue directory after a successful move; driver core: add KUnit coverage for device_move glue references |
| GPU power | drm/msm/a6xx: build MX dependency votes from the GPU OPP table; pmdomain: qcom: rpmhpd: skip the retention level for GMXC |
| Firmware framebuffer | drm/simpledrm: describe firmware scanout bandwidth with an OPP table (the binding change is to be split out) |
| Type-C | dt-bindings: usb: fsa4480: describe DIO4485 compatible; usb: typec: fsa4480: support DIO4485 and propagate I/O failures; soc: qcom: pmic_glink_altmode: encode DP assignments and honor route failures |
| Audio | ASoC: qcom: sdw: avoid orphan streams on direct DMIC links; ASoC: lpass-tx-macro: use the channel mask for mixer state and mute (with its regression tests) |
| Pin control | pinctrl: qcom: sm8750: describe the TLMM I2C pull-up bit |
| Backlight | backlight: ktz8866: report register errors and support distinct instances |
| New drivers | Input: add NT36532E cascade THP transport and firmware tests; HID: nanosic: add initial piano I2C and HID transport. Both lack power management |
| WCN7860 | dt-bindings: regulator: qcom,qca6390-pmu: document the WCN7860 PMU; dt-bindings: net: bluetooth: add the Qualcomm WCN7860 binding; wifi: ath12k: declare WCN7860 firmware files; dt-bindings: net: wireless: qcom,ath12k: allow a MAC address property; wifi: ath12k: retrieve MAC address from system firmware if needed. These depend on the imported WCN7860 series |
| Charger | power: supply: qcom_battmgr: release the GLINK client after its users; soc: qcom: pmic_glink: add a client for the Xiaomi MCA charger firmware; power: supply: add a read-only driver for the Xiaomi MCA charger firmware (with KUnit tests); dt-bindings: soc: qcom: pmic-glink: document the Xiaomi Pad 8 Pro |
| Board | the `arm64: dts: qcom: piano:` series (board DTS) |

Local-only changes: soc: qcom: restore the DT root identity replaced by ABL
and the configuration fragments. The supervised diagnostic DT variants are
kept on the kernel `piano/diag` branch, not on `piano/dev`.

Imported community work keeps its original authorship; its upstream status
follows its authors: Adreno 830 driver, bindings, DT nodes and cooling
(Jie Zhang, Akhil P Oommen, Gaurav Kohli; Qualcomm), SM8750 GPU clock and
SMMU nodes (ROCKNIX), WCN7860 ath12k, PCI power control, power sequencing and
Bluetooth (Teguh Sobirin), ath12k QDSS configuration download (Gianni
Spadoni), the PCIe `#iommu-cells` fix of `qcom_pcie_config_sid_1_9_0()`
(Manivannan Sadhasivam, FROMLIST), APR/GPR, q6v5 handover and UFS fixes
(Junhao Xie, via BigfootACA/linux), Novatek NT36532 panel driver (Junjie Cao),
and DSC slice-per-packet support (Alexander Koskovich, Jonathan Marek).
