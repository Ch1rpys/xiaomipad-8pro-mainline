# Status

Last updated: 2026-10-08. The component support matrix is in the
[README](../README.md#support-matrix). This page records the test
configuration, known issues, roadmap and upstreaming state.

## Test configuration

All hardware statuses refer to this configuration only.

| Item | Value |
|---|---|
| Device | Xiaomi Pad 8 Pro (`piano`), model 25091RP04C (China), SoC SM8750P, 16 GB RAM, 512 GB UFS; bootloader unlocked |
| Stock build | OS3.0.303.0.WPYCNXM |
| Kernel | `7.2.6-piano+`, kernel repository commit `b136d29d2`; fragments `piano-diagnostic.config`, `piano-desktop-diag.config`, `piano-persistent.config`; DTB `sm8750-xiaomi-piano-desktop.dtb`; 1071 modules. [`kernel/source.json`](../kernel/source.json) now pins `65bf28a0f`, whose package `linux-image-7.2.6-piano1` (unique release, see [`kernel/abi.json`](../kernel/abi.json)) is built but not installed |
| Integration | this repository at `48964a9`; `piano-device-support` 0.1+20261008.1 |
| Userspace | Ubuntu 26.04 Desktop ARM64; Mesa 26.2.0 with `mesa/a830-speedbin.patch` |

Verification basis: the installed system was checked with a debug image set
that is identical to the release set except for the kernel command line (it
adds a USB console and a session timeout). Display output was confirmed both
visually and with DPU frame counters. The release image set boots from slot A.

## Known issues

1. **Slot retry count.** ABL decrements slot A's retry counter on every boot,
   and Ubuntu does not yet mark the slot as successfully booted. After about
   seven Ubuntu boots ABL stops booting slot A. `fastboot --set-active=a` or
   re-flashing an image set resets the counter.
2. **No charging.** The battery discharges under Linux, including with USB
   connected. Charge in Android and keep at least 40 % before switching to
   Linux.
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
7. **Kernel updates are slow.** The kernel package trigger takes about
   12.5 minutes on the device (dracut about 8 minutes, the kdump-tools initrd
   about 4 minutes). `piano-boot-update` then rebuilds the Ubuntu image set
   in `/var/lib/piano/switch/ubuntu/`; it does not write partitions, and the
   new set takes effect only after an explicit switch.
8. **Generic kernels.** Kernel packages inherited from the Desktop image
   (`linux-image-7.0.0-14-generic`, `linux-generic-hwe-26.04`) remain
   installable and receive initrds, but cannot boot piano.
9. **Boot log errors without observed effect:** UFS `EE_CONTROL` write
   returns -22; systemd `bpf-restrict-fs` fails to load; ADSP "Handover
   signaled, but it already happened"; one Bluetooth frame reassembly error
   (-84) during firmware download; a qcom-apm command timeout; two snap user
   services fail.
10. **Debug entry.** `piano-debug.service` and `piano-debug-timeout.service`
    are installed and enabled but run only when the kernel command line
    contains `piano.debug=1`; that mode provides an unauthenticated root
    shell over USB. Release images do not set it.
11. **Module ABI.** `CONFIG_MODVERSIONS` is disabled. Install the kernel image
    and modules from the same build only.
12. **Package notices.** Locally generated packages contain third-party
    binaries (BusyBox, AOSP tools, Mesa) but no
    `/usr/share/doc/<package>/copyright` files yet. Keep them local.

## Roadmap

In priority order:

1. Mark slot A as successfully booted after a completed Ubuntu boot.
2. Wi-Fi: establish the PCIe0 PHY supply mapping and enable ath12k for the
   WCN7860.
3. Charging: support the vendor charger protocol (MCA), which differs from
   the upstream `battmgr` interface.
4. Publish the installer (partitioning, filesystem creation, boot-profile
   generation); add package copyright files, an avbtool fetch script and
   Python-independent `init_boot` output.
5. Native display: MDSS/DPU/DSI with the NT36532 panel driver and both
   KTZ8866 backlight controllers, providing brightness and screen-off/wake.
   External display depends on this step.
6. Suspend and resume (s2idle and deep) with display, touch, keyboard,
   Bluetooth and UFS recovery.
7. Speaker playback, microphone recording and UCM, USB host and Type-C
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
| WCN7860 | dt-bindings: regulator: qcom,qca6390-pmu: document the WCN7860 PMU; dt-bindings: net: bluetooth: add the Qualcomm WCN7860 binding; wifi: ath12k: declare WCN7860 firmware files. These depend on the imported WCN7860 series |
| Board | the `arm64: dts: qcom: piano:` series (board DTS) |

Local-only changes: soc: qcom: restore the DT root identity replaced by ABL,
the diagnostic DT variants and the configuration fragments.

Imported community work keeps its original authorship; its upstream status
follows its authors: Adreno 830 driver, bindings, DT nodes and cooling
(Jie Zhang, Akhil P Oommen, Gaurav Kohli; Qualcomm), SM8750 GPU clock and
SMMU nodes (ROCKNIX), WCN7860 ath12k, PCI power control, power sequencing and
Bluetooth (Teguh Sobirin), Novatek NT36532 panel driver (Junjie Cao), and DSC
slice-per-packet support (Alexander Koskovich, Jonathan Marek).
