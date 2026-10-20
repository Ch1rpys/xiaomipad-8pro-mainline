# Iris VA-API package

The build recipe consumes the exact archive and patches in `source.json`.
The driver uses the upstream Meson build, the system libva ABI, and normal
V4L2 stateful decoder interfaces. It does not replace Firefox, Chrome,
FFmpeg or Mesa.

Build with Python 3.12+, Meson, Ninja, an ARM64 C/C++20 toolchain and an
explicit Meson cross file. The target sysroot needs libva ≥ 2.23, libdrm,
EGL, GLES and GBM development files. Its executable wrapper must run ARM64
unit tests (QEMU user mode is sufficient). `build-deps.json` records the
reference build's dependency URLs, versions and hashes; extract development
packages into a host sysroot. Use compiler `-ffile-prefix-map` flags to remove
host paths, including paths embedded by C++ standard-library assertions.

```sh
python3 tools/build-iris-vaapi-deb.py \
  --source-archive /path/to/pinned-source.tar.gz \
  --cross-file /path/to/arm64.ini \
  --output /path/to/build-output
```

The output contains an ARM64 deb, the complete corresponding source archive,
test logs and a manifest. Unchanged inputs reuse the Meson output. Changed
inputs require a new output directory.

The driver package owns only its libva plugin, the MSM discovery symlink and
license/source records. It contains no maintenance scripts, browser flags,
global environment overrides, services or kernel installation hooks.
Removal uses normal package removal. Browser defaults belong to desktop
integration and must retain user overrides.

H.264, HEVC and VP9 are the upstream decoder families. AV1 is not advertised
by default. A successful build does not establish browser sandbox, hardware
decoding, resolution switching or presentation support on a device.

Chromium snap is outside this integration: its confinement and bundled
libraries require separate package integration.
