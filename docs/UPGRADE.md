# Upgrading an Existing Installation

[中文](UPGRADE.zh-CN.md) ｜ [Project home](../README.md) ｜ [Fresh installation](INSTALL.md) ｜ [Switching and recovery](FLASHING.md)

This page upgrades an installed Ubuntu to a new release's kernel and device packages without
reinstalling, repartitioning or erasing data. Prerequisites: the final step of
[INSTALL.md](INSTALL.md) is done (`/etc/piano` holds `boot-profile.json`, `boot-signing.pem` and
`boot-partitions.json`), developer mode can be enabled, and the battery is at 40 % or more.

The release asset `piano-ubuntu-<version>-packages.zip` is the upgrade package: its `debs/`
directory holds every project package installed in that release's image. Always install the
whole set together, never a single package.

## Upgrading from v0.3.2 to v0.4.0

Follow the same steps below using `piano-ubuntu-v0.4.0-packages.zip`. Install the entire package set together, including Linux 7.2.10-piano26 and its matching camera loopback package. Reboot to activate the touch fixes. Keep the previous kernel installed and retain its rollback boot set. No repartitioning or root-image flash is needed.

## Upgrading from v0.3.1 to v0.3.2

Follow the same steps below using `piano-ubuntu-v0.3.2-packages.zip` and install the entire package set together. The kernel remains Linux 7.2.10-piano25. Reboot so the snap graphics provider is refreshed and applications pick up the new driver. No repartitioning or root-image flash is needed.

## Upgrading from v0.3.0 to v0.3.1

Follow the same steps below using `piano-ubuntu-v0.3.1-packages.zip`. Install the entire package set together, including Linux 7.2.10-piano25 and its matching camera loopback package; retain the previous kernel and rollback boot set. No repartitioning or root-image flash is needed.

After reboot, the power-button action appears in Settings → Power. The default is suspend; a previously chosen personal power-button setting is kept. Camera apps now use the automatically started camera service.

## Upgrading from v0.2.0 to v0.3.0

Install the complete v0.3.0 `packages.zip` together: kernel, device support and desktop, Mesa and snap graphics, `piano-camerad`, and `piano-camera-loopback-*` matching the new kernel, plus the included firmware, sensor and authentication packages. No root-image flash, repartitioning or new per-unit extraction is required.

System suspend and GNOME's default idle policy are now enabled; disk hibernation remains disabled. Existing personal power settings are preserved and can be changed in Settings → Power. Reboot after installation to activate the new kernel, WirePlumber camera isolation and session color-profile unit. Rear focus is fixed. Keep the previous kernel and matching modules for rollback.

## 1. Download and verify

On the host, download `piano-ubuntu-<version>-packages.zip` and `SHA256SUMS.assets` from the
release page into an empty directory:

```bash
sha256sum -c --ignore-missing SHA256SUMS.assets    # expect one "OK" line for packages.zip
unzip piano-ubuntu-<version>-packages.zip            # yields debs/
```

## 2. Keep a rollback

The upgrade replaces the current boot set with one for the new kernel; the old set is kept
automatically as `ubuntu.prev`. Save an independent copy as well, so that a later upgrade cannot
rotate it away. On the tablet:

```bash
sudo cp -a /var/lib/piano/switch/ubuntu /var/lib/piano/rollback-$(uname -r)
```

Also keep copies of the current Ubuntu set and the Android set on the host as described in
[FLASHING.md "Image sets"](FLASHING.md#image-sets); they are the basis for recovery from Fastboot.

## 3. Copy to the tablet

Enable developer mode in a terminal on the tablet, then copy from the host:

```bash
# tablet
sudo piano-devmode on
# host
python3 "$REPO/tools/piano-devmode-ssh.py" --serial <SERIAL> --check     # expect "... ready"
scp -r debs <USER>@192.168.88.2:
```

## 4. Install

Run the installation in a transient unit so that a dropped SSH session cannot abort it; the
kernel package rebuilds the initrd, which takes about 10 minutes.

```bash
sudo apt update
sudo systemd-run --unit=piano-upgrade --setenv=DEBIAN_FRONTEND=noninteractive \
  apt-get install -y /home/<USER>/debs/*.deb
journalctl -f -u piano-upgrade
# expect "Piano boot image set prepared for <new kernel>" and "Slot A now holds store/ubuntu",
# finally "piano-upgrade.service: Deactivated successfully."
sudo dpkg --audit                          # expect no output
sudo piano-boot-switch verify              # expect exit code 0
```

## 5. Reboot and check

```bash
sudo systemctl reboot
```

After logging in again:

```bash
uname -r                                   # expect the new kernel
sudo piano-boot-switch status              # expect "occupant": "ubuntu"
sudo piano-slot-success --check            # expect "state": "already-successful"
sudo piano-devmode off                     # once the host connection is no longer needed
```

The previous kernel package stays installed; the rollback set needs it. Once the new release has
proven itself, remove it with `sudo apt purge linux-image-<old version>`.

## Rollback

- **Ubuntu still boots:**
  ```bash
  sudo piano-boot-switch import-ubuntu --from /var/lib/piano/rollback-<old version>   # expect "result": "imported"
  sudo piano-boot-switch to-ubuntu --reboot                                           # writes the old set back and reboots
  ```
- **Ubuntu does not boot:** hold Power + Volume Down for Fastboot and write the old Ubuntu set
  saved on the host:
  ```bash
  python3 "$REPO/tools/piano-switch.py" --serial <SERIAL> --images <old ubuntu set> --rollback <android-set>
  fastboot -s <SERIAL> reboot
  ```
  Or switch to Android first (`--images <android-set> --rollback <old ubuntu set>`) and sort it
  out from there.
