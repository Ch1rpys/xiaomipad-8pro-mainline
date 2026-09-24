# Ubuntu for Xiaomi Pad 8 Pro

Native mainline-based Linux and Ubuntu ARM64 for Xiaomi Pad 8 Pro
(piano / SM8750). [中文](README.zh-CN.md)

P04/P05 verified Linux 7.2.6 RAM boot, bidirectional USB2 NCM diagnostics, exact
runtime identity and DT capture, and timed return to Android on piano. P08 additionally
verified the Ubuntu 26.04 RAM root and native systemd. P12/P13 now render the native
GNOME desktop and terminal; the operator confirmed the internal display on P13,
with 200% scaling. Automatic Android return passed. Real touch/input remains
unverified, and there is no installable image.

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
P12 declares the missing display AXI clock dependency for simpledrm, and P13 has
physical desktop confirmation. Firmware scanout is still used; native panel power
management remains incomplete. Explicit diagnostic sessions can use a locked,
disposable user and standard GDM autologin entirely in the RAM overlay.

Local DSP firmware packaging from user-supplied inputs is available and archive-checked;
the proprietary package is not redistributable under this repository's license.
Isolated APT preparation has resolved and downloaded the native dracut update set,
without installing it. Unprivileged ext4 assembly preserves archive metadata;
the ext4 artifact has only run in QEMU. The separate pristine SquashFS has now booted
native Ubuntu on piano in a temporary RAM overlay, not a persistent installation.
The failed P06 handoff and offline-reproduced BusyBox naming fix are not hidden by P08 success.
See the build notes.

Original project code is MIT unless stated otherwise. Imported code retains its
original license and attribution in NOTICE and LICENSES, including GPL-2.0-only
diagnostic tools. See CONTRIBUTING.md.
