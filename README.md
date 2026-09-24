# Ubuntu for Xiaomi Pad 8 Pro

Native mainline-based Linux and Ubuntu ARM64 for Xiaomi Pad 8 Pro
(piano / SM8750). [中文](README.zh-CN.md)

P04/P05 verified Linux 7.2.6 RAM boot, bidirectional USB2 NCM diagnostics, exact
runtime identity and DT capture, and timed return to Android on piano. Persistent
logs still contain damaged bytes; there is no installable image or working Ubuntu desktop.

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
Bounded successful sessions do not validate panic or early-hang recovery.
P03 ACM was not tested; NCM reuses the host DHCP path without tty permission changes.
P05 registers simpledrm/fbcon and accepts VT writes on hardware, but physical
display output is not yet confirmed. Native panel power management remains incomplete.

Local DSP firmware packaging from user-supplied inputs is available and archive-checked;
the proprietary package is not redistributable under this repository's license.
Isolated APT preparation has resolved and downloaded the native dracut update set,
without installing it. Unprivileged ext4 assembly preserves archive metadata;
the root has run Ubuntu systemd and selected commands in QEMU, not GNOME or piano
hardware. It is not an installable tablet image. See the build notes.

Original project code is MIT unless stated otherwise. Imported code retains its
original license and attribution in NOTICE and LICENSES, including GPL-2.0-only
diagnostic tools. See CONTRIBUTING.md.
