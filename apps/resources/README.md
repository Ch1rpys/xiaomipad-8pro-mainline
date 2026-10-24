# Resources telemetry

Generic Linux telemetry patches for the GNOME Resources source locked in
[source.json](source.json): CPU-prefixed thermal zones, msm DRM fdinfo usage,
Adreno identity/devfreq/temperature, and per-battery power_supply temperature.
No device-specific configuration or distribution package manager is required.
Missing battery temperature readings hide the row; temperature units follow
Resources preferences.

Apply to the pinned upstream revision in a clean checkout:

```sh
git clone https://gitlab.gnome.org/GNOME/Incubator/resources.git
cd resources
git checkout ae2e129c0e29b3543b923a1dc5ea02aee9daf15a
git am /path/to/xiaomipad-8pro-mainline/apps/resources/patches/*.patch
```

Build with Resources' upstream Meson/Cargo instructions and your distribution's
build dependencies, then package with that distribution's normal tooling.
Ubuntu's older source package needs the context/API adaptations described in
[the Ubuntu recipe](../../ubuntu/resources/README.zh-CN.md).

Patches are GPL-3.0-or-later, like Resources; see [COPYING](COPYING).
Remove each patch once the selected upstream version includes equivalent
functionality, and remove distribution pins/version overrides together.
