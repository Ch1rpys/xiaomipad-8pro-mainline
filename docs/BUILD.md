# Building

[中文](build.zh-CN.md) | [Project overview](../README.md) | [Release artefacts](RELEASE.md)

How the release is built from pinned inputs: kernel → ABI entry → kernel package → device and
firmware packages → boot image set → root image → release directory. None of the tools needs root
or accesses a tablet. A successful build is not a hardware result. Each step's expected output and
the identities to record are in [AGENT-GUIDE.md](AGENT-GUIDE.md) §3.

## Host

Linux x86_64. Commands run from the root of this repository.

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
| Mesa | 26.2.0 and `mesa/a830-speedbin.patch`, [mesa/source.json](../mesa/source.json) |
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
  such as `v0.1.0-preview` are never taken for the upstream version.
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
the backup is manual in v0.1.

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
  --download dracut device-tree-compiler openssh-server fake-hwclock systemd-zram-generator
python3 tools/build-rootfs-image.py --squashfs out/ubuntu-desktop-pristine/ubuntu-desktop.squashfs ... \
  --boot-profile <boot-profile.json> --boot-key <release signing key> --output out/rootfs-<version>
# expect "state": "ROOT_IMAGE_BUILT_OFFLINE_CHECKS_PASS_NOT_BOOTED"
```

Firefox APT inputs are prepared in [ubuntu/firefox/source.json](../ubuntu/firefox/source.json)
for the unmodified ARM64 deb from [Mozilla](https://support.mozilla.org/en-US/kb/install-firefox-linux),
so a future image can use its own Mesa stack instead of the snap graphics runtime.
`prepare-ubuntu-apt.py --mozilla-firefox` verifies the pinned key, archived signed index and package
hashes with priority 1000. **This is not enabled in the image builder:** the frozen Desktop base is
already snap-preseeded, with Firefox 8105 registered in `state.json`, an installed snap and pending
hooks. Editing only `seed.yaml` and its payloads cannot remove that installed snap; the seed-only
migration stopped before building an image. No Firefox GPU or device result is claimed.

`fake-hwclock` is a dependency of piano-ubuntu-desktop 0.1+20261010.6. Download
`systemd-zram-generator` only for a kernel with `CONFIG_ZRAM` (7.2.6-piano7 and later): without the
module the boot waits 90 s for `/dev/zram0` (QEMU, 7.2.6-piano6), and `build-rootfs-image.py`
refuses the mismatch. The guest also purges Ubuntu's generic kernels and `kdump-tools`, sets the
hostname `xiaomipad-8pro`, deletes the base's APT indexes and ends with `fstrim`
([RELEASE.md](RELEASE.md#what-the-image-contains)).

The boot profile is reduced to the stock-build fields before use. The image has no account, no
machine ID, no SSH host keys and no file of any unit; it is not byte-reproducible because dpkg and
dracut record times.

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
