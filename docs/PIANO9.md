# Piano9 packaged candidate

Piano9 pins kernel `3ef018a0e9d5ac6e9a1b22ae85dd8e7b5c243166`: the installed
piano8 source plus Iris and read-only SDAM2. The preceding Iris RAM test decoded
150/150 1080p H.264 frames with matching hashes. That result does not establish
device acceptance of this newly packaged ABI.

`kernel/source.json` selects `7.2.6-piano9`; the existing kernel builder applies
that release to `CONFIG_LOCALVERSION` after the kernel-owned configuration
fragments. No kernel commit is needed just to allocate the package ABI.
`kernel/abi.json` binds the exact commit and resulting configuration to
`7.2.6-9.1`. The configuration differs from piano8 only in its release name;
all modules are rebuilt for piano9. Never rename or reuse piano8 modules.

The accompanying packages contain:

- `piano-ubuntu-desktop`: GStreamer good and bad plugins, supplying
  `v4l2h264dec` and `h264parse`, alongside the existing desktop policy.
- `piano-device-support`: the clean bounded RAM-return helper and current
  dracut integration, including the board's Iris firmware name; it requires
  firmware package 0.5 or newer.
- `piano-mipps-auth`: optional `ExecStopPost` cleanup; an unsupported cleanup
  write does not mark successful authentication as a failed unit.
- `piano-local-firmware` 0.5: locked signed VPU35 firmware in addition to the
  existing firmware and audio topologies.

## A. RAM check from Android

Use the local bundle README and its serial-bound `run.py` after verifying
SHA256SUMS and embedded DTB identity. The header-v2 image must be smaller than
93,000,000 bytes. The existing runner checks identity, backups and fresh battery,
performs one RAM boot, and observes return to Android. It uses the installed
root and its existing test autologin, handing over matching modules read-only.
The timeout at kernel uptime 600 seconds now stops desktop/user services,
syncs and requests normal systemd shutdown to the bootloader. The forced
fallback starts 45 seconds later if shutdown cannot complete.

## B. Install on the ordinary piano8 root

After observing RAM recovery, enter ordinary piano8 Ubuntu by the existing
[switching procedure](FLASHING.md). Do not install while the RAM module bind
is active. Preserve the verified Android set and a separate
`/var/lib/piano/piano9-rollback` copy of the piano8 Ubuntu set before installation;
keep the piano8 kernel package too. Install all five bundle packages together.

The root must have enabled Ubuntu archive sources and current package indexes.
Run `sudo apt-get update` before `sudo apt-get install /var/tmp/piano9/debs/*.deb`.
On the previously tested root, plugins-bad was unavailable until the archive
indexes were refreshed. Use the Ubuntu packages; no separate GStreamer stack
is supplied. GStreamer availability does not by itself prove browser decoding.

Run `sudo dpkg --audit`, `sudo piano-boot-update 7.2.6-piano9` and the standard
boot-set verification. Check the release, native DTB, firmware, image hashes
and `msm.separate_gpu_kms=0`; persistent boot must have no diagnostic timeout.
An explicit update can rotate `ubuntu.prev` again, so retain the independent
rollback copy. Do not install the RAM-debug triplet.

## C. Cold-boot acceptance

From the host, use the existing developer-mode transport and the actual user:

```sh
python3 tools/piano-cold-boot-accept.py run --serial "$PIANO_SERIAL" \
  --user "$PIANO_USER" --kernel-release 7.2.6-piano9 --out "$PRIVATE_CAPTURE"
```

The tool prompts for sudo authentication (or accepts its existing private
password-file mechanism), saves two captures from the same boot and requires
the late capture at uptime >=200 seconds. It now accepts an explicit release;
its historical `PIANO8_*` capture field names remain unchanged. The default is
piano8 for existing callers. No threshold is relaxed: simpledrm <1 s,
switch_root <=10 s, GDM/GMU <=20 s, matching modules, >=2 GB/s memory copy,
dual 144 Hz scanout, zero GPU/clock/DSI errors, healthy units and a real user
Wayland session remain required. Hardware input and wall charging remain
separate acceptance tasks.

On failure preserve evidence, then use `piano-boot-switch import-ubuntu --from
/var/lib/piano/piano9-rollback` and the standard verified switch/recovery path.
This build task performs no device access, installation, slot writes or tags.
