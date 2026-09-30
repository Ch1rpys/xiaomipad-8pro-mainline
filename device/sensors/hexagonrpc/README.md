# HexagonRPC reference input

Use the upstream project at the commit in `source.json`, with the listed patches
in order. These are fixes to the original marshaller and tests, not a replacement
sensor protocol implementation. There is no firmware, calibration or installed
piano service in this directory.

The first patch fixes type selection, empty-sequence slots, output buffer counts,
sequence cursors, and packed field accesses. Eleven added tests check explicit
wire buffers through a substituted ioctl, including failed allocations and I/O.
The second patch fixes an unaligned reverse-tunnel length store and undefined
zero-length operations in the existing test. The wire representation is retained.

Apply the patches to a clean checkout of the pinned upstream commit, verify the
patch hashes from `source.json`, then use its normal Meson build:

```sh
meson setup build /path/to/patched/hexagonrpc --prefix=/usr --buildtype=release \
  --cross-file /path/to/arm64-cross.ini
meson compile -C build
meson test -C build --print-errorlogs
DESTDIR=/path/to/stage meson install -C build --no-rebuild
```

For host memory checks, use a separate native build with
`-Db_sanitize=address,undefined`. All 14 tests passed both with these host checks
and as ARM64 binaries under qemu-user. The original source fails the new sequence
regressions. No test opens a DSP device; the full sensor service is not validated.

Keep the upstream library, daemon and service files under their own build and
packaging. A native distribution package recipe can consume the staging tree;
piano-specific firmware/registry inputs and permission policy are separate.
The staged upstream services have not been enabled or accepted as product policy.
P23 deliberately omits FastRPC, so it cannot exercise this daemon yet.

Licenses remain per upstream file: the marshaller source is LGPL-3.0-or-later;
its public header, tests and reverse-tunnel code are GPL-3.0-or-later. The new test
is GPL-3.0-or-later. See the retained file headers, `NOTICE`, and `LICENSES`.
Drop the local patches when upstream contains the fixes and the same regressions
pass; do not maintain an independent copy of the source tree here.
