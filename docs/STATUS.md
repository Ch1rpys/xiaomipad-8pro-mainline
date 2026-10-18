# Release history and current support

Current release: **v0.5.0**. See the [README](../README.md#hardware-support) or
[中文 README](../README.zh-CN.md#硬件支持) for the hardware support tables and usage instructions.

## Current support

Ubuntu 26.04 GNOME runs natively with Android dual boot. Supported features include
GPU-accelerated desktop and snap applications, 3200×2136 display with 60/90/120/144 Hz
selection, Night Light, touch input, magnetic keyboard, Wi-Fi, Bluetooth pairing and
audio, speaker playback, microphone recording, front and rear cameras, sensors,
auto-rotation, USB host / OTG with docks, USB storage, keyboards and mice, charging and
system suspend. The power button locks the screen by default and GNOME offers Power Saver,
Balanced and Performance modes.

H.264/H.265/VP9 hardware decoding is available; automatic use depends on the player.
H.264/H.265 hardware encoding is verified at 1080p and 4K. Multi-finger gestures and
volume keys are untested, and charger compatibility is limited. Keep the default
speaker volume cap because speaker protection is absent. System time is set
from the network after boot. Sensor calibration defaults are included; see the
[calibration instructions](../device/sensors/README.zh-CN.md) to use your own tablet's calibration.

Not yet supported: stylus, fingerprint, USB-C external display, disk hibernation and
hardware clock writes.

## Test configuration

Results are from one Xiaomi Pad 8 Pro (`piano`), model 25091RP04C (China), with
Snapdragon SM8750P, 16 GB RAM, 512 GB UFS and an unlocked bootloader. The stock build
is OS3.0.303.0.WPYCNXM on slot A. Software is Linux 7.2.10 with the piano patches,
Ubuntu 26.04 Desktop ARM64 and Mesa 26.2 for desktop and snap applications; sensors
use the default calibration. The kernel input is pinned in
[kernel/source.json](../kernel/source.json). The v0.2.0 fresh installation was
verified on this unit; later versions were tested on the installed system. These
results do not establish support for other models, capacities or accessories.

## Completed work by release

### v0.5.0

- USB host / OTG for docks, USB storage, keyboards and mice, including charging while using a powered dock.
- The power button locks the screen by default and wakes the lock screen when pressed again.
- Power Saver, Balanced and Performance modes in GNOME, with Balanced as the default.
- Showtime and GStreamer playback dependencies installed by default, with software decoding fallback.
- The touch service retries with increasing delays instead of giving up when its stream cannot start.

### v0.4.0

- Touch works after switching to 120 or 60 Hz and reliably returns after screen on.
- Screen wake is about 0.3 seconds faster.
- Includes the camera and video display improvements from v0.3.2.

### v0.3.2

- Removed diagonal stripes in camera previews and video frames in GTK applications.
- Reduced CPU use during camera preview while retaining the optional BGRx output.

### v0.3.1

- Removed the brief garbled frame when turning the screen off, locking or suspending.
- Both cameras become available automatically in camera applications, with a working Snapshot preview.
- Touch recovers automatically after a touch service stream error.
- The power-button action is configurable in Settings → Power, with suspend as the default.

### v0.3.0

- Added GNOME Night Light and front/rear camera capture with fixed rear focus.
- Enabled system suspend with timer, power-button, keyboard and cover-open wake.
- Added keyboard wake with the screen off and from suspend.
- Added H.264/H.265/VP9 hardware decoding and H.264/H.265 encoding at 1080p and 4K.
- Improved refresh-rate switching, screen off/on, charging restoration after suspend,
  microphone recording level and desktop/snap graphics compatibility.
- Supported upgrades from v0.2.0 without repartitioning or reflashing the root image.

### v0.2.0

- Delivered the first fully verified fresh installation and Android/Ubuntu switching
  from Ubuntu, Android's KernelSU module and host Fastboot.
- Added native 3200×2136 display at 144 Hz, adjustable brightness, screen off/on and
  touch recovery after screen on.
- Enabled Adreno 830 acceleration for the desktop and snap applications, including Firefox,
  and verified 1080p H.264 hardware decoding.
- Delivered Wi-Fi, microphone recording, speaker playback with capped volume,
  magnetic keyboard input, sensors and auto-rotation with the keyboard detached.
- Added battery and temperature reporting, installation assistance and upgrade documentation.

## Usage notes

- Browser video currently uses software decoding.
- Bluetooth occasionally needs reconnecting before data or audio works again.
- The rear camera has fixed focus; nearby subjects may be blurry and color tuning is limited.

Installation and maintenance instructions are in [INSTALL.md](INSTALL.md),
[UPGRADE.md](UPGRADE.md) and [FLASHING.md](FLASHING.md).
