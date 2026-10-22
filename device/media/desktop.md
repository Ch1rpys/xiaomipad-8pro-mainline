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

