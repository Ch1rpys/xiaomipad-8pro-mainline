# Desktop media packages

Ubuntu 26.04 uses Showtime as its default video player (the
[Ubuntu Desktop package](https://packages.ubuntu.com/resolute/ubuntu-desktop)
recommends `showtime`). `piano-ubuntu-desktop` explicitly depends on it so it is
also installed when recommendations are disabled. Its standard package pulls
in the GL and GTK4 GStreamer sinks; the desktop package also depends on:

| Package | Purpose |
|---|---|
| `gstreamer1.0-plugins-base` | Playback infrastructure and base plugins |
| `gstreamer1.0-plugins-good` (already required) | `libgstvideo4linux2.so`, including stateful V4L2 decoder probing |
| `gstreamer1.0-plugins-bad` (already required) | Video parsers, including H.264/H.265 |
| `gstreamer1.0-libav` | Software decoding fallback; depends on the system `libavcodec62`, also available to native Firefox |

Package metadata: [Showtime](https://packages.ubuntu.com/resolute/showtime),
[good files](https://packages.ubuntu.com/resolute/arm64/gstreamer1.0-plugins-good/filelist),
[bad files](https://packages.ubuntu.com/resolute/arm64/gstreamer1.0-plugins-bad/filelist),
[libav](https://packages.ubuntu.com/resolute/gstreamer1.0-libav).
Use the signed Ubuntu snapshot dependency resolver described in
[RELEASE.md](../../docs/RELEASE.md) to pin the complete distribution package set.
These dependencies supply a playback stack; automatic Iris selection by
Showtime on a fresh user session remains a device acceptance check. No global
plugin-rank, browser hardware-decode or sandbox override is installed.

## Optional mpv candidate (not packaged)

[mpv/mpv.conf](mpv/mpv.conf) is a proposed `/etc/mpv/mpv.conf` fragment for mpv
0.41, restricted to H.264/HEVC/VP9. It is **pending device validation** and is
not copied by `build-device-debs.py`. No default mpv/Celluloid dependency is added.
Before enabling it, check `mpv --hwdec=help` and verify actual Iris decoding,
correct frames, seek, subtitles, audio/video synchronization and software
fallback for each allowed codec. AV1 is excluded. The system configuration is
read before user configuration; see the
[mpv v0.41 manual](https://github.com/mpv-player/mpv/blob/v0.41.0/DOCS/man/options.rst).

Celluloid's libmpv configuration loading is an explicit preference, not a
promise that it reads the CLI's system configuration. In Preferences → Config
Files, enable “Load mpv configuration file” and select the file; alternatively
use its Extra MPV Options. See the [Celluloid FAQ](https://celluloid-player.github.io/faq.html).
Celluloid requires its own playback acceptance before distributing a default.
