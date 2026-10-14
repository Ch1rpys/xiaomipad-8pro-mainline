# Piano panel color profile

`piano-ubuntu-desktop` enables the standard user unit
`piano-panel-srgb.service` at graphical-session startup. It runs only in a
GNOME Wayland session on Piano. It watches colord's device-added signal until
the current user's embedded DSI-1 display exists (30-second unit deadline).

For an enabled, uninhibited device with no profiles, it associates the installed
`/usr/share/color/icc/colord/sRGB.icc` using colord's **soft** relationship. It
never makes a profile default explicitly, imports an ICC file, changes EDID,
enables a disabled device, or changes an existing user/system selection. Hard
user/system associations take precedence even if one is added concurrently.
The association lasts with Mutter's temporary device; the helper exits after
handling it. Removing the integration does not leave a hard mapping behind.
This is a generic sRGB description, not panel calibration.

Mutter 50.1 source supports this without a Mutter patch:

- [`meta-color-store.c:507–510`](https://gitlab.gnome.org/GNOME/mutter/-/blob/50.1/src/backends/meta-color-store.c#L507): no EDID skips only device-profile generation.
- [`meta-color-device.c:499–536`](https://gitlab.gnome.org/GNOME/mutter/-/blob/50.1/src/backends/meta-color-device.c#L499): colord connection proceeds independently; no EDID leaves no pending EDID-profile work.
- [`meta-color-device.c:148–220`](https://gitlab.gnome.org/GNOME/mutter/-/blob/50.1/src/backends/meta-color-device.c#L148) and [`396–430`](https://gitlab.gnome.org/GNOME/mutter/-/blob/50.1/src/backends/meta-color-device.c#L396): connection and changes load colord's default into `assigned_profile`, then update the device.
- [`meta-color-device.c:1420–1476`](https://gitlab.gnome.org/GNOME/mutter/-/blob/50.1/src/backends/meta-color-device.c#L1420): a ready device with an assigned profile generates and applies its temperature LUT.
- [`meta-color-profile.c:468–520`](https://gitlab.gnome.org/GNOME/mutter/-/blob/50.1/src/backends/meta-color-profile.c#L468): a profile without VCGT still generates the black-body temperature ramp.

The audited upstream tag resolves to
`8e9bb806da4a6a4fc87aa4a481b228dba6735cbd`.
Colord [1.4.8 profile ordering](https://github.com/hughsie/colord/blob/1.4.8/src/cd-device.c#L486)
puts hard mappings first; its [client default lookup](https://github.com/hughsie/colord/blob/1.4.8/lib/colord/cd-device.c#L483)
returns no default when disabled or inhibited, which is why checking only for
an absent default would be insufficient.

The helper uses Gio to call colord's system D-Bus API. The package depends on
`colord`, `colord-data` and `python3-gi`; it does not require the Colord typelib. For an already running RAM desktop, run
`systemctl --user daemon-reload` and `systemctl --user start piano-panel-srgb.service`
**as its logged-in user** after installing the package. Inspect that user's
`journalctl --user -u piano-panel-srgb.service` and the colord default profile
before running the encoder-CRC night-light check. Offline source/API/package
checks do not establish hardware color correction.
