# Ubuntu for Xiaomi Pad 8 Pro

Native mainline-based Linux and Ubuntu ARM64 for Xiaomi Pad 8 Pro
(piano / SM8750). [中文](README.zh-CN.md)

This project is in offline research. There is no installable image and no
hardware functionality has been verified on a piano device.

This repository owns Ubuntu integration, device userspace, build and installation
tools, and user documentation. Kernel drivers, device trees and configuration
belong in an independent Linux repository; its public remote is not established.

## Available Tool

Run `sh tools/fetch-aosp-mkbootimg.sh` to obtain a pinned AOSP boot-image tool
checkout. Git, Python 3, sha256sum and initial network access are required.
This does not access a tablet or create a bootable piano image.

Offline platform compilation, a bounded diagnostic ramdisk and original Ubuntu
Desktop layer preparation are available; see [build notes](docs/build.zh-CN.md).
The reference QRD/MTP device trees are not valid piano boot inputs.

Original project code is MIT unless stated otherwise. Imported code retains its
original license and attribution in NOTICE and LICENSES, including GPL-2.0-only
diagnostic tools. See CONTRIBUTING.md.
