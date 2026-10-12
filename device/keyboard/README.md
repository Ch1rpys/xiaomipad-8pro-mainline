# Piano keyboard integration

The kernel owns the WN8030 transport, firmware download, HID keyboard and
consumer keys, LED class controls, attachment switch and power callbacks.
This accessory has no touchpad: its DT sets `nanosic,no-touchpad` and the driver
never creates a touchpad HID device. `SW_TABLET_MODE` is the inverse of the
MCU's connected bit; it is independent of the folio Hall policy.

Use `CONFIG_HID_NANOSIC_WN8030=m`, the complete matching module package and
normal distribution udev/kmod OF modalias loading. No keyboard startup service,
module blacklist, manual GPIO/supply setup or dependency on a display/touch
service is needed. GENI/GPI and regulator dependencies are represented in DT
and handled by driver probe/deferred probe. A service becoming active would
not establish keyboard functionality.

The device requests `nanosic/piano/MCU_Upgrade.bin` via `firmware-name`.
`firmware/piano-input.json`, consumed by `tools/firmware_payload.py`, pins the
83,436-byte OS3.0.303.0.WPYCNXM stock extraction to SHA-256
`c03d6b650cb85a983359c6686d831875df10ee1206fd31afc1403baefeb7e407`.
The existing `piano-local-firmware` package already installs these bytes.
No community firmware download, duplicate blob or global alias is required.

Standard interfaces:

- Keyboard/consumer events: evdev through HID; Caps Lock uses HID output.
- Attach/detach: `Xiaomi Keyboard Tablet Mode`, `EV_SW/SW_TABLET_MODE`.
- Backlight: `/sys/class/leds/nanosic::kbd_backlight/brightness` (0–100).
- Mic mute LED: `/sys/class/leds/nanosic::micmute/brightness` (0–1).
- Community `nanosic_hinge`/`nanosic_auth` interfaces are retained, with no
  optional angle/authentication daemon enabled by this integration.

Driver source presence and offline tests do not validate physical LEDs,
reconnection, suspend, wake or energy use. Keep system suspend disabled until
its independent display and platform prerequisites are met.

## Provenance and reuse decision

Kernel: `blu-sharky/linux-piano`, commit
`f8afe7ff7127f46f5339fdaf5c24ecbffbfbb92b`, #17, GPL-2.0-only,
`drivers/hid/hid-nanosic-wn8030.c`, binding and `nanosic_hinge.h`.
The imported commit retains bluseliu50's authorship and the original
map220v/ianchb credits and Signed-off-by trailers. The local integration
keeps the board's own electrical settings and checked firmware/parser core.

Userspace reviewed (not copied): `blu-sharky/debian-piano`, commit
`a75f8c5d5fa099d65c171ac839c2e3bb6c63ec45`,
`boot/dtbo-piano-keyboard.dts`, `rootfs/overlay/usr/lib/piano/keyboard-start`,
`rootfs/overlay/usr/lib/systemd/system/piano-keyboard.service`,
`rootfs/overlay/etc/modprobe.d/piano.conf` and its `80-drivers.rules`.
Their service explicitly loads the module because their image suppresses OF
module autoload. Piano's Ubuntu integration retains standard autoload, so that
workaround and its waits/ordering are unnecessary here. The overlay is wiring
reference only; it is not shipped or applied. This README is included in the
existing desktop package as integration documentation; it adds no service.
