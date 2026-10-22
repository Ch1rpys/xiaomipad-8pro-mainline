# Building

[中文](build.zh-CN.md) | [Project overview](../README.md) | [Release artefacts](RELEASE.md)

How the release is built from pinned inputs: kernel → ABI entry → kernel package → device and
firmware packages → boot image set → root image → release directory. The native root-image chroot
requires root; the other tools run unprivileged. No build tool accesses a tablet. A successful build is not a hardware result. Each step's expected output and
the identities to record are in [AGENT-GUIDE.md](AGENT-GUIDE.md) §3.

## Host

Linux x86_64 for the guest backend, or native AArch64 as root for the chroot backend.
Commands run from the root of this repository.

| Stage | Tools |
|---|---|
| Kernel | Git, Python 3, GCC, an AArch64 GNU cross compiler, make, bc, bison, flex, pkg-config, OpenSSL and libelf development files, gzip, cpio, kmod (`depmod`), flock; ccache optional |
| Boot DTB and boot set | `device-tree-compiler` (`fdtget`, `fdtput`), `python3-libfdt`, AOSP libufdt `ufdt_apply_overlay`, AOSP `avbtool.py` (no fetch script yet), `openssl` |
| Packages | `dpkg-deb`, `python3-debian`, `aarch64-linux-gnu-g++`, `nlohmann-json3-dev`, `m4`, `alsatplg` |
| Mesa | Meson 1.9, Ninja, Mako, PyYAML, Python packaging, Bison, Flex, a native `glslangValidator`, an ARM64 GCC/G++ cross toolchain, and a Meson cross file with an explicit ARM64 sysroot (libdrm, zlib, zstd, expat, Wayland 1.24 and wayland-protocols, X11/XCB development packages from Ubuntu 26.04) |
| Ubuntu base | `7z`, `unsquashfs`, squashfs-tools-ng 1.2 (`sqfs2tar`), `apt`, `python3-apt` |
| Root image and release | e2fsprogs 1.47.4 built with libarchive and NLS (`mke2fs`, `e2fsck`, `debugfs`, `dumpe2fs`), `img2simg`, `sgdisk`, `zip`, QEMU `qemu-system-aarch64` |

```bash
sh tools/fetch-aosp-mkbootimg.sh       # pinned checkout in tools/local/aosp-mkbootimg
sh tools/fetch-busybox-arm64.sh        # expect ".../usr/bin/busybox: OK"
```

## Pinned inputs

| Input | Pin |
|---|---|
| Kernel | [linux-sm8750-piano](https://github.com/yzddmr6/linux-sm8750-piano), branch `piano/dev`; commit and configuration fragments in [kernel/source.json](../kernel/source.json), releases in [kernel/abi.json](../kernel/abi.json) |
| Firmware | [firmware/](../firmware/README.md), locked by `firmware/piano-*.json` |
| Mesa | 26.2.0 and `mesa/piano-fixes.patch`, [mesa/source.json](../mesa/source.json) |
| Ubuntu | 26.04 Desktop ARM64 ISO, SHA-256 `c2afd538d66fdd77377d03f1ed2ac76a34f1c116baecc9a8170d68f833121f57`; [ubuntu/26.04.sources](../ubuntu/26.04.sources); packages from a dated [snapshot](https://snapshot.ubuntu.com/) |
| Device userspace | `device/*/source.json` |

Owner inputs come from your own tablet and are never committed: the stock base DTB and DTBO entry,
the boot profile and the signing key ([INSTALL.md](INSTALL.md#3-collect-your-units-files)).

## 1. Kernel

```bash
git clone --branch piano/dev https://github.com/yzddmr6/linux-sm8750-piano ../linux
git -C ../linux checkout "$(python3 -c 'import json; print(json.load(open("kernel/source.json"))["commit"])')"
CONFIG_FRAGMENT_EXTRA="arch/arm64/configs/piano-desktop-diag.config arch/arm64/configs/piano-persistent.config arch/arm64/configs/piano-release.config" \
BUILD_MODULES=1 KERNEL_SOURCE=../linux OUT_DIR="$PWD/out/kernel-release" bash tools/build-kernel.sh
# expect "Piano kernel build complete: .../out/kernel-release/build-result.json (boot packaging is separate)"
```

- `build-kernel.sh` refuses a tree whose HEAD differs from `kernel/source.json` or that has
  uncommitted tracked changes. The base fragment is merged first, then `CONFIG_FRAGMENT_EXTRA` in
  order, `piano-release.config` last.
- The upstream base is the tag of the version in the kernel's top-level Makefile
  (`python3 tools/kernel_tag.py ../linux` prints `v7.2.6`); it must exist and be an ancestor of HEAD.
  `build-kernel.sh` and `build-kernel-deb.py` both use it, so project tags on the kernel repository
  are never taken for the upstream version.
- Reuse the OUT directory for incremental builds (ccache is used when installed); a different
  toolchain or source location needs a new one.
- Without `piano-release.config` the release keeps a diagnostic suffix and cannot be packaged.

## 2. ABI entry

Every packaged kernel has a unique release `<version>-piano<N>`. Take the next `N` whenever the
kernel commit or the resulting `.config` changes, including DTS-only and toolchain changes; never
reuse or lower it.

1. In the kernel repository set `CONFIG_LOCALVERSION="-piano<N+1>"` in
   `arch/arm64/configs/piano-release.config` and commit.
2. Set `commit` in `kernel/source.json` to the new kernel HEAD and build (step 1).
3. Run the packager (step 4). For an unrecorded release it stops and prints the entry; append it
   with `"upload": 1` to `releases` in `kernel/abi.json`, commit `kernel/source.json` and
   `kernel/abi.json` together and run the packager again.

## 3. Boot DTB

ABL applies the stock DTBO to the boot DTB. `prepare-boot-dtb.py` prepares the desktop DTB against
your stock base DTB (from `vendor_boot_a`) and DTBO entry (from `dtbo_a`); extracting these two from
the backup is manual.

```bash
python3 tools/prepare-boot-dtb.py \
  --mainline-dtb out/kernel-release/arch/arm64/boot/dts/qcom/sm8750-xiaomi-piano-desktop.dtb \
  --stock-base <stock base DTB> --stock-overlay <stock DTBO entry> \
  --ufdt <ufdt_apply_overlay> --output out/boot-dtb
```

Prepare a new one whenever the desktop DTB changes.

## 4. Kernel package

```bash
python3 tools/build-kernel-deb.py --kernel-source ../linux --kernel-out out/kernel-release \
  --boot-dtb out/boot-dtb/piano-boot.dtb --maintainer 'Name <email>' --output out/kernel-deb-<N>
# expect JSON with "package": "linux-image-7.2.6-piano<N>", "deb" and "deb_sha256"
```

The package holds the kernel, all DTBs, `piano-boot.dtb` and the matching modules. Its maintainer
scripts run Ubuntu's dracut hook and the piano boot hook. Identical inputs give a byte-identical deb.

## 5. Device and firmware packages

```bash
# touch processing, static ARM64
mkdir -p out/json-include && cp -r /usr/include/nlohmann out/json-include/
make -C device/piano-thp OUT="$PWD/out/piano-thp-arm64" CXX=aarch64-linux-gnu-g++ \
  JSON_INCLUDE="$PWD/out/json-include" LDFLAGS=-static
# Mesa 26.2.0 with the A830 patch
MESA_SOURCE=<Mesa checkout at mesa/source.json> CROSS_FILE=<arm64 cross file> \
  OUT_DIR="$PWD/out/mesa" bash tools/build-mesa.sh
# piano-device-support, piano-mesa, piano-ubuntu-desktop
python3 tools/build-device-debs.py --output out/device-debs --version 0.1+<YYYYMMDD>.<n> \
  --thp-live out/piano-thp-arm64/piano-thp-live --mesa-build out/mesa \
  --busybox tools/local/busybox-arm64/usr/bin/busybox --avbtool <avbtool.py>
# capture topology (AudioReach checkout at device/audio/source.json), then piano-local-firmware
mkdir -p out/audio
m4 -I <audioreach-topology checkout> device/audio/Piano-Capture-Diag.m4 > out/audio/Piano-Capture-Diag.conf
alsatplg -c out/audio/Piano-Capture-Diag.conf -o out/audio/Piano-Capture-Diag-tplg.bin
python3 tools/build-firmware-deb.py --topology out/audio/Piano-Capture-Diag-tplg.bin \
  --card-topology out/audio/Xiaomi-Pad-8-Pro-tplg.bin \
  --maintainer 'Name <email>' --output out/firmware-deb
```

- `build-mesa.sh` refuses a Mesa HEAD other than `mesa/source.json`. Mesa installs under
  `/opt/piano/mesa-26.2.0` and does not replace Ubuntu's Mesa packages.
- `build-firmware-deb.py` takes `firmware/` by default; `--firmware-tree <dir>` uses your own
  extraction in the same layout. Every file is checked against its lock.
- Raise `--version` on every device package rebuild so that dpkg installs it as an upgrade.

## 6. Boot image set

`build-persistent-boot.py` builds the signed v4 `boot`, `init_boot` and `vendor_boot` images for
slot A from a root's kernel, its dracut initrd and `piano-boot.dtb`, plus `boot-ram-check.img` for
`fastboot boot`. On an installed tablet `piano-boot-update` runs it after each kernel update.

```bash
python3 tools/build-persistent-boot.py \
  --kernel <root>/boot/vmlinuz-<release> --kernel-release <release> \
  --dtb <root>/usr/lib/linux-image-<release>/piano-boot.dtb --initrd <root>/boot/initrd.img-<release> \
  --profile <boot-profile.json> --root-partuuid <linux_rootfs PARTUUID> --bt-address-file <bluetooth-address> \
  --mkbootimg tools/local/aosp-mkbootimg/mkbootimg.py --avbtool <avbtool.py> --key <boot-signing.pem> \
  --output out/ubuntu-set-<release>
```

- A set for your unit carries your addresses (`--bt-address-file`, `--wlan-address-file`) and serial.
- The release set is unit-independent: `--root-partlabel linux_rootfs --no-serial` and no address
  files. `build-rootfs-image.py` builds it in step 7.
- `--debug` and the other debug options add an unauthenticated root shell over USB; never write a
  debug set to slot A for normal use ([AGENT-GUIDE.md](AGENT-GUIDE.md) §3.6, §7.2).
- `--maintenance` builds only `boot-ram-maintenance.img`, the RAM image for writing the partition
  table, from a maintenance initramfs (`tools/prepare-maintenance-payload.py` and
  `build-initramfs.sh` with `MAINTENANCE_DIR`); the commands are in [AGENT-GUIDE.md](AGENT-GUIDE.md) §4.6.

## 7. Ubuntu base and root image

Extract the two official Desktop layers and merge them into a pristine TAR and SquashFS, without
root:

```bash
UBUNTU_ISO=<ubuntu-26.04-desktop-arm64.iso> OUT_DIR="$PWD/out/ubuntu-desktop-layers" \
  bash tools/prepare-ubuntu-desktop.sh
mkdir -p out/desktop-tars
sqfs2tar --root-becomes . --no-skip out/ubuntu-desktop-layers/minimal.squashfs > out/desktop-tars/minimal.tar
sqfs2tar --root-becomes . --no-skip out/ubuntu-desktop-layers/minimal.standard.squashfs \
  > out/desktop-tars/minimal.standard.tar
python3 tools/merge-desktop-tars.py \
  --base out/desktop-tars/minimal.tar --desktop out/desktop-tars/minimal.standard.tar \
  --output out/ubuntu-desktop-pristine
```

Then fetch the Ubuntu packages added to the base from a signed snapshot, and build the 60 GiB root
image with the packages of steps 4 and 5. `build-rootfs-image.py` installs them in a disposable QEMU
ARM64 guest (the target never boots), builds the release boot set from the image's initrd, checks
the result offline and writes `root.sparse.img`; it takes about 35 minutes. The full commands are in
[RELEASE.md](RELEASE.md#building-a-release):

```bash
python3 tools/prepare-ubuntu-apt.py --rootfs out/ubuntu-desktop-pristine/ubuntu-desktop.squashfs \
  --snapshot <YYYYMMDDTHHMMSSZ> --output out/apt-release \
  --mozilla-firefox --download dracut device-tree-compiler openssh-server fake-hwclock systemd-zram-generator
python3 tools/build-rootfs-image.py --squashfs out/ubuntu-desktop-pristine/ubuntu-desktop.squashfs ... \
  --boot-profile <boot-profile.json> --boot-key <release signing key> --output out/rootfs-<version>
# expect "state": "ROOT_IMAGE_BUILT_OFFLINE_CHECKS_PASS_NOT_BOOTED"
```

Firefox is the unmodified ARM64 deb from [Mozilla's APT repository](https://support.mozilla.org/en-US/kb/install-firefox-linux),
so it can use the image's Mesa stack. `--mozilla-firefox` authenticates the key, archived signed index
and exact package version/hash in [ubuntu/firefox/source.json](../ubuntu/firefox/source.json); the image
retains the Mozilla source and priority 1000 for updates. The official preseeded Firefox snap and
snapd state remain untouched during construction. After first-boot seeding, the desktop package's
`piano-firefox-snap-remove.service` removes only Firefox with `snap remove --purge`, marks success
and has a five-minute timeout. It does not delay the display manager. The dock uses `firefox.desktop`;
Thunderbird remains a snap. Snap removal and Firefox GPU rendering require a device test.

`fake-hwclock` is a dependency of the current piano-ubuntu-desktop package. Download
`systemd-zram-generator` only for a kernel with `CONFIG_ZRAM`: without the
module the boot waits 90 s for `/dev/zram0` (QEMU), and `build-rootfs-image.py`
refuses the mismatch. The guest also purges Ubuntu's generic kernels and `kdump-tools`, sets the
hostname `xiaomipad-8pro`, deletes the base's APT indexes and ends with `fstrim`
([RELEASE.md](RELEASE.md#what-the-image-contains)).

The boot profile is reduced to the stock-build fields before use. The image has no account, no
machine ID, no SSH host keys and no file of any unit; it is not byte-reproducible because dpkg and
dracut record times.

### Root-image backends

`build-rootfs-image.py --backend chroot` accepts only native `aarch64` with EUID 0 and runs the
shared package steps in a loop-mounted ext4, with private proc/sys/dev/pts binds and temporary
run/tmp. Mount and network namespaces keep build activity separate from the host; an exit trap
unmounts in reverse order. It has no QEMU or binfmt dependency. Omitting `--backend` selects chroot
for native ARM64 root and guest otherwise; `--backend guest --qemu …` selects the QEMU guest
explicitly. The 60 GiB raw ext4 remains a sparse host file in both cases.

## 8. Release directory

Optionally boot the image in QEMU with `check-rootfs-boot.py`, then assemble the release:

```bash
python3 tools/build-release.py --rootfs-build out/rootfs-<version> \
  --boot-check out/rootfs-<version>-boot/result.json \
  --forbid-file <your bluetooth-address> --forbid-file <your wlan-address> --forbid-file <your boot-profile.json> \
  --output out/release-<version>
(cd out/release-<version> && sha256sum -c SHA256SUMS)
```

`--forbid-file` scans every output for identifiers of your unit. The release must be on the same
filesystem as the root image build. Layout, contents and installation: [RELEASE.md](RELEASE.md) and
[INSTALL.md](INSTALL.md).

## Graphics for core24 snaps

`piano-snap-graphics` supplies one `piano-mesa-2404` content provider for installed
`gpu-2404` consumers. This gives those strict snaps the A830 Mesa without replacing
each application with a deb. The existing Mozilla Firefox deb policy is unchanged;
`mesa-2404` stays installed for rollback. The provider uses the desktop's exact
`mesa/source.json` commit and patch, compiled against the separately locked
`mesa/snap/core24-sdk.json` ABI and overlaid on the complete ARM64 mesa-2404 rev 1166
locked in `mesa/snap/mesa-2404.json`. This full content contract matters: consumers
run Canonical's gpu-2404 cleanup and omit libraries supplied by mesa-2404, including
non-Mesa X11/XML dependencies. A Mesa-only provider passed its own pixel test but
broke Thunderbird and App Center on the device. The packager now
rejects missing stock files or changes outside the Mesa overlay and snap metadata.
All stock wrapper/hooks, component metadata, runtime files and notices are retained.
The slot exports only `$SNAP`; the optional kernel-content directory is not a
second export on piano. Mesa uses release / `-O3` / `b_ndebug=true` / LTO off.
The earlier assertion-enabled provider aborted while compiling application GLSL
(`ir_constant::is_value`); a clear-only pixel test did not exercise that path.
Imported tooling provenance and its GPL-2.0-only licence are recorded in `mesa/snap/provenance.json`.

```bash
python3 tools/build-mesa-root.py --target gpu-2404 --native-nir \
  --base-snap <mesa-2404_1166.snap> \
  --mesa-source <Mesa Git checkout> --cache out/gpu-snap-inputs \
  --work out/gpu-snap-build --output out/gpu-snap-package --jobs 6
python3 tools/validate-mesa-snap.py --build out/gpu-snap-package \
  --sdk-root out/gpu-snap-build/root --stock-provider <mesa-2404_1166.snap> \
  --base out/gpu-snap-inputs/ubuntu-base-24.04.4-base-arm64.tar.gz \
  --output out/gpu-snap-validation --core24 <frozen-core24-arm64.snap> \
  --consumer <thunderbird_1045.snap> --consumer <snap-store_1368.snap> \
  --gnome-runtime <gnome-46-2404_154.snap>
python3 tools/build-device-debs.py --snap-graphics-only \
  --snap-graphics-build out/gpu-snap-package --output out/gpu-snap-deb \
  --version 0.1+<YYYYMMDD>.<n>
```

Obtain the locked ARM64 provider with `snap download mesa-2404 --revision=1166`
on ARM64, or extract `var/lib/snapd/seed/snaps/mesa-2404_1166.snap` from the frozen
Desktop SquashFS; always check the lock's SHA-256. For a packaging-only correction,
`tools/package-mesa-snap.py --reuse-mesa-build <previous-build> --base-snap <snap>
--output <new-output>` reuses only Mesa files verified against the previous build
and snap receipts, preserving the same source/patch without recompilation. The
stock component monitor and hooks remain upstream; the install hook disables
that monitor when its optional kernel content plug is disconnected.

Packaging/validation need Python 3, PyYAML and squashfs-tools. The build needs
qemu-user ARM64 binfmt and unprivileged user namespaces; native NIR generation needs the SDK Python minor version (3.12), Mako, MarkupSafe and
Ninja on the host (`--ninja /path/to/ninja` if it is not on PATH). By default, target compilation runs in the pinned ARM64 SDK.

With an ARM64 cross-toolchain, replace `--native-nir` above with
`--cross-file <arm64-core24.ini>` to run generators, compilation and packaging
on the build host. The standard Meson cross file must point its sysroot,
target pkg-config directories, C/C++ headers and library paths at `root/`
under this build's `--work`, rather than a desktop Ubuntu sysroot. The host
needs the compiler, Mako, PyYAML, Ninja, native wayland-scanner and
glslangValidator; the builder reuses the pinned Meson wheel. QEMU remains
necessary for SDK preparation. The build records the cross-file SHA-256 and
target package versions and checks that Meson configured an ARM64 target.
Do not combine this option with `--native-nir`. Both paths use the same Mesa
source, patch and profile options, with core24 target headers and libraries.

`--resume`
continues that attempt's frozen recipe, without changing its inputs. The offline
pixel check explicitly requires softpipe and is not a GPU or sandbox test.
Validation uses the actual seeded core24 runtime, checks every provider ELF,
and can check Thunderbird/App Center binaries plus their dlopened graphics/proxy
libraries with the GNOME runtime. `--old-provider <previous.snap>` first reproduces
the missing-library failure. These checks do not launch the GUI or prove confinement.

Also run the GLSL regression against the final snap. It compiles a shader with
integer constants and nested min/max through the provider's mapped libgallium,
then checks the rendered pixel. `--old-provider` is optional; when supplied it
must reproduce exit 134 at `ir.cpp:1603`, while the new provider must compile,
link and draw without an assertion. Shader caching is disabled. Only the small
probe is built; neither Mesa nor the provider snap is rebuilt:

```bash
python3 tools/test-snap-graphics-glsl.py \
  --provider <new-piano-mesa-2404.snap> --old-provider <previous-provider.snap> \
  --core24 <frozen-core24-arm64.snap> --sdk-root out/gpu-snap-build/root \
  --output out/gpu-snap-glsl
```

This is a softpipe/qemu-user regression, not application, confinement or A830
acceptance. Matching release flags avoids the observed assertion; it does not
claim to fix the underlying Mesa assertion logic. `--keep-build` on the Mesa
builder retains unstripped objects for later crash analysis.

Pass the resulting deb as one additional `--deb` to `build-rootfs-image.py` along
with the existing device packages. Its postinst only enables the unit. On the
first boot, `piano-snap-graphics.service` waits for `snapd.seeded.service`, installs
the local snap with `--dangerous`, then processes each installed `gpu-2404` plug:
disconnect previous slots first, connect piano if needed, then run
`/usr/lib/snapd/snap-discard-ns` for that consumer. Content connections are additive;
the previous connect-first order could leave a stale `gpu-2404-2` mount. Discard
also runs for an already connected consumer so its next launch recreates the
namespace with one content mount. The previous provider snaps stay installed.
It records completion only after success, has a five-minute bound and no retries.
After installing a new snap, close affected applications, run
`sudo piano-snap-graphics-connect`, then reopen them. Consumer refreshes retain manual connections;
new consumers are not automatically intercepted. When consumers move to
`gpu-2604`/core26, rebuild a provider for that ABI/interface before connecting them;
this core24 provider does not serve `gpu-2604`. Retire it when the distribution
provider supports A830 and passes the same hardware/confinement checks.

## Bounded RAM return regression

`piano-debug-timeout.service` uses the kernel-uptime `piano.debug_timeout`
deadline (600 seconds for RAM hardware checks). Its helper stops the display
manager and user slice, syncs, and requests a normal systemd reboot with
`--reboot-argument=bootloader`. PID1 stops services and systemd-shutdown
unmounts/remounts the ext4 root read-only. The host still waits for Fastboot
and performs its existing recovery; capture and image-size limits are unchanged.

A child armed before any blocking shutdown work forces the same bootloader
reboot after 45 seconds. `DefaultDependencies=no` and
`SurviveFinalKillSignal=yes` (systemd >=255; Ubuntu 26.04 supplies 259) keep it
alive through shutdown. Explicitly stopping the timeout unit still cancels its
whole control group. A forced fallback can leave a dirty journal if filesystem
shutdown was blocked. The clean path must finish before that fallback.

New `build-native-display-initrd.py` builds refresh the helper/unit from this
source and carry them through `/run` into the installed root; they do not depend
on that root already containing the fix. Existing frozen RAM images stay unchanged.

Run the ARM64 exit/journal regression on the host, with a clean disposable-input
Ubuntu ext4 image and a kernel with built-in VirtIO block/ext4 support:

```sh
python3 tools/test-debug-timeout-qemu.py \
  --kernel /path/to/Image --rootfs /path/to/ubuntu.ext4 \
  --qemu /path/to/qemu-system-aarch64 --busybox /path/to/arm64/busybox \
  --gen-init-cpio /path/to/linux-out/usr/gen_init_cpio \
  --debugfs /path/to/debugfs --e2fsck /path/to/e2fsck \
  --output /path/to/new-test-output
```

This uses the same virt/TCG, serial and `-no-reboot` exit method as the Ubuntu
handoff harness. It pivots from RAM into a writable ext4 copy and exercises real
Ubuntu PID1 with test display-manager/user-slice services. It retains guest disk
writes and asserts `e2fsck -n` reports clean **and** `needs_recovery` is clear;
it never replays the journal to make a test pass. It also checks the unchanged
`bootloader` reboot reason and both fixture stop markers. This is not a GDM,
Fastboot or tablet hardware test.

`--scenario old-force` is a negative control that must detect a dirty journal.
`--scenario blocked-stop` holds a stop job; `--scenario blocked-shutdown` holds
an executable systemd-shutdown hook after the final kill and filesystem cleanup.
Both must force a bootloader reboot at the 45-second bound; the latter must
still have a clean journal. `--seconds 60` can shorten these failure fixtures
without changing the production 600-second budget.
