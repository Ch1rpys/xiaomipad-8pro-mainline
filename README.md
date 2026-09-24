# Ubuntu for Xiaomi Pad 8 Pro

Native mainline-based Linux and Ubuntu ARM64 for Xiaomi Pad 8 Pro
(piano / SM8750). [中文](README.zh-CN.md)

P02 reached Linux 7.2.6 RAM PID1 and returned to Android using its 60-second timer.
Recovered logs contain damaged bytes. Complete log integrity, runtime DT and USB
interaction are not verified; there is no installable image or working Ubuntu system.

This repository owns Ubuntu integration, device userspace, build and installation
tools, and user documentation. Kernel drivers, device trees and configuration
belong in an independent Linux repository; its public remote is not established.

## Available Tool

Run `sh tools/fetch-aosp-mkbootimg.sh` to obtain a pinned AOSP boot-image tool
checkout. Git, Python 3, sha256sum and initial network access are required.
This does not access a tablet or create a bootable piano image.

An initial piano DTS, bounded diagnostic ramdisk, packaging-only stock overlay
isolation and RAM boot-image generation are available, alongside unprivileged
Ubuntu Desktop layer merging that preserves inode metadata; see [build notes](docs/build.zh-CN.md).
The bounded P02 RAM test does not validate panic or early-hang recovery.
P02 had USB, display and storage disabled. The P03 offline candidate adds USB2
device-mode ACM diagnostics; this is not yet verified on hardware or a working system.

Original project code is MIT unless stated otherwise. Imported code retains its
original license and attribution in NOTICE and LICENSES, including GPL-2.0-only
diagnostic tools. See CONTRIBUTING.md.
