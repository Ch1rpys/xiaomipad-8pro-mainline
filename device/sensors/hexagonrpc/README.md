# HexagonRPC reference input

Use the upstream project at the commit in `source.json`, with the listed patches
in order. These extend the original marshaller and file service, not a replacement
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

The third patch adds read-only ODM and additional vendor sensor paths and an
explicit `-w DIR` registry mapping. Only that copied directory permits real
create/write/append/update/remove operations; links and non-regular write targets
are rejected, and other mappings remain read-only. Its new test drives the real
apps_std method handlers and checks actual file bytes and confinement. The
Qualcomm method ABI and upstream PR #21 informed the patch; fake-success stubs
are not used.
All 15 tests now pass under ARM64 qemu-user and native ASan/UBSan (leak checking
is excluded for the upstream process-lifetime virtual directory tree).

Keep the upstream library, daemon and service files under their own build and
packaging. A native distribution package recipe can consume the staging tree;
piano-specific firmware/registry inputs and permission policy are separate.
The staged upstream services have not been enabled or accepted as product policy.
The ADSP baseline diagnostic omits FastRPC. A separate device test reached
this daemon through the secure ADSP sensorspd node but failed registry
initialization at file-service gaps. The file-service patch checks described
here are offline tests, not device validation.

Licenses remain per upstream file: the marshaller source is LGPL-3.0-or-later;
its public header, tests and reverse-tunnel code are GPL-3.0-or-later. The new test
is GPL-3.0-or-later. See the retained file headers, `NOTICE`, and `LICENSES`.
Drop the local patches when upstream contains the fixes and the same regressions
pass; do not maintain an independent copy of the source tree here.

The fourth patch maps version, temporary registry output and parsed-file
cache one level above the inner registry entries, matching the device log.
Both `-R .../sensors/registry` and explicit `-w DIR` describe the
whole parent containing `registry/`, `sns_reg_version` and `parsed_file_list.csv`.
The existing write confinement is retained; tests replay the actual sibling
paths and 108 temporary-file opens.

Patch 0005 imports upstream PR #27 commit f0dfd5095d3b7defc3b368f227337bfc6d6aef42
unchanged (original author/date/Sign-off retained). It fetches
reverse-listener input beyond the 256-byte prefix with get_in_bufs2, method 5.
This was cleanly cherry-picked onto 598b591a in an isolated source repository;
it is not claimed to be merged upstream. Patch 0006 adds length validation,
partial-buffer cleanup, consistent empty error-reply sizing and ioctl-boundary
file-write regressions. 4 KiB/64 KiB are read back from real scratch files;
24 ARM64 tests pass. No custom ION path is introduced: fd=-1 invoke arguments
use the inspected kernel's copied DMA-backed payload path, as the existing
marshaller does for input/output buffers. Real DSP/DMA acceptance remains untested.
