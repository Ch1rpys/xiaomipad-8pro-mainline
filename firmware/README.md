# Firmware

Stock firmware for the Xiaomi Pad 8 Pro (`piano`), stored under the paths the mainline kernel
requests below `/usr/lib/firmware`. The packaging tools use this tree by default.

## Origin

All files come from stock build **OS3.0.303.0.WPYCNXM** and are byte-identical to the stock files.
Only the Wi-Fi files are renamed, to the names `ath12k` requests (the mapping is in `piano-wlan.json`).
The source partitions are written by system updates and are the same on every unit with this build.
Per-unit data is excluded (see below).

| Directory | Files | Loaded by | Stock source | Lock |
|---|---|---|---|---|
| `qcom/sm8750/piano/` | 56: `adsp.mdt`, `adsp.b01`–`adsp.b54` (no `b27`), `adsp_dtb.mdt`, `adsp_dtb.b01` | `qcom_q6v5_pas` (audio DSP) | `modem_a` FAT, `image/` | `piano-os3.0.303.0.json` |
| `qcom/` | `gen80000_sqe.fw`, `gen80000_gmu.bin`, `gen80000_aqe.fw` | `msm` (Adreno 830) | `vendor_a`, `firmware/` | `piano-gpu.json` |
| `qcom/sm8750/xiaomi/piano/` | `gen80000_zap.mbn` (signed for this model) | `msm` zap shader | `odm_a`, `firmware/` | `piano-gpu.json` |
| `qca/` | 27: `gngbtfw20.mbn`, `gngbtnv20.bin` and 25 board-specific `gngbtnv20.bXX` | `hci_qca` (WCN7860 Bluetooth, ROM 0x20) | `bluetooth_a` FAT, `image/` | `piano-bluetooth-rom20.json` |
| `ath12k/WCN7860/hw2.0/` | `amss.bin`, `m3.bin`, `aux_ucode.bin`, `regdb.bin`, `qdss.cfg`, `board.bin` | `ath12k` (WCN7860 Wi-Fi) | `modem_a` FAT, `image/peach/` | `piano-wlan.json` |
| `novatek/piano/` | `novatek_nt36532_piano_fw_csot.bin` | `nt36532e-thp` (touch) | `odm_a`, `firmware/` | `piano-input.json` |
| `nanosic/piano/` | `MCU_Upgrade.bin` | `hid-nanosic` (keyboard bridge) | `odm_a`, `firmware/` | `piano-input.json` |

Each lock pins the name, size and SHA-256 of its files. `piano-os3.0.303.0.json` also pins the CDSP
images and service maps of the same build. They are not shipped because the current kernel does not
load them. `board.bin` is the stock board file for the China region (`bd_p81.elf`). Units sold for
other regions use a different stock board file.

**Not included:**
- touch calibration, which `tools/extract-thp-calibration.py` generates per device;
- the Bluetooth address, the Wi-Fi MAC address (`persist`) and other per-unit calibration;
- stock files the current kernel does not load (CDSP, video, other board files and panel variants);
- the audio capture topology `qcom/sm8750/Piano-Capture-Diag-tplg.bin`, which is built from
  [`device/audio`](../device/audio/README.md).

## Packaging and using your own extraction

`tools/build-firmware-deb.py` builds `piano-local-firmware` from this tree. The package contains
every locked file and the capture topology built from `device/audio`. Each file is checked against
its lock:

```sh
python3 tools/build-firmware-deb.py --topology out/audio/Piano-Capture-Diag-tplg.bin \
  --maintainer 'Your Name <you@example.org>' --output out/firmware-deb
```

To use files from your own device instead, copy them from its stock partitions into a directory
with the same layout. Rename the Wi-Fi files as listed in `piano-wlan.json`. Then add
`--firmware-tree /path/to/your/tree`. Files outside the locks are ignored, and a missing or
different file stops the build. A different stock build therefore needs updated locks.
`tools/stage-firmware.py --firmware-dir /path/to/modem/image` stages the DSP files alone from the
flat stock `image/` directory.

## Licence

`SPDX-License-Identifier: LicenseRef-Proprietary-Firmware`
([text](../LICENSES/LicenseRef-Proprietary-Firmware.txt)). This applies to every file in the
subdirectories. This README and the `piano-*.json` locks are MIT, like the rest of the project.

The vendors have granted no redistribution licence. The files are distributed unmodified for
interoperability, so that owners of this device can run mainline Linux on it. The licences of this
repository do not cover them. They will be removed at a rights holder's request.
