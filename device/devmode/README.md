# Developer mode: SSH over the USB cable

Release images expose no USB function, so a host cannot reach a running
Ubuntu session. Developer mode is an administrator's switch that adds one:
the USB NCM network link of the debug channel and an OpenSSH login on it,
with the normal (non-debug) boot. It is **off by default** and stays off until
an administrator turns it on.

Status: offline only. The units pass `systemd-analyze verify` (host systemd
255 and the Ubuntu 26.04 systemd 259), the OpenSSH configuration passes
`sshd -t` (OpenSSH 9.6 and the Ubuntu 26.04 OpenSSH 10.2), and the gadget
script passes a real configfs test in QEMU with the release kernel and
`dummy_hcd`. Nothing of this has run on the tablet yet.

## Turning it on and off

```
sudo piano-devmode on       # systemctl enable --now piano-devmode.service
sudo piano-devmode off      # systemctl disable --now piano-devmode.service
piano-devmode status
```

The enablement state of `piano-devmode.service` is the only persisted switch;
`on` keeps developer mode on across reboots until `off`. An installer that
offers developer mode enables the same unit when the user opts in
(`systemctl --root=/target enable piano-devmode.service`); nothing else needs
to be written.

Developer mode needs the OpenSSH server. `piano-device-support` only
*recommends* `openssh-server`, and `piano-devmode on` and the unit refuse to
start with a clear message when `/usr/sbin/sshd` is missing. The Ubuntu
desktop image does not include it. Installing `openssh-server` enables and
starts Ubuntu's own `ssh.socket`, which listens on every address; disable it
so that SSH stays on the USB link only:

```
sudo systemctl disable --now ssh.socket ssh.service
```

While `ssh.socket` or `ssh.service` runs, the developer-mode socket cannot
bind port 22 (`piano-devmode status` warns about it).

Debug boots (`piano.debug=1`) keep the debug channel, which owns the same USB
identity and addresses; developer mode does not start in them, even when
enabled.

A desktop switch can use `pkexec /usr/sbin/piano-devmode on|off`; the polkit
action `io.github.piano.devmode` asks for administrator authentication every
time.

## Connecting from the host

```
python3 tools/piano-devmode-ssh.py USER                 # login shell
python3 tools/piano-devmode-ssh.py -t USER sudo piano-reboot-bootloader
python3 tools/piano-devmode-ssh.py --check              # link ready?
```

`USER` is an account on the tablet. The tool finds the host interface by the
host MAC of [`initramfs/network.json`](../../initramfs/network.json) and the
USB device above it (development IDs `1d6b:0104`, serial `piano-*`; use
`--serial` when more than one tablet is attached), waits up to `--wait`
seconds (default 20) for the DHCP address, and runs
`ssh USER@192.168.88.2`. The host's network manager normally takes the lease
by itself. If it did not, the tool prints the commands, for example:

```
sudo ip link set dev enx020000880001 up
sudo ip address replace 192.168.88.10/24 dev enx020000880001
```

Run as root it applies them itself. It sends nothing else to the tablet.

`sudo piano-reboot-bootloader` restarts the tablet into Fastboot
(`systemctl reboot --reboot-argument=bootloader`). It loads
`nvmem_qcom-spmi-sdam` and `nvmem-reboot-mode`, as the debug channel's expiry
timer does, and refuses to reboot when no `nvmem-reboot-mode` device is
bound, since the reboot would then return to slot A. `sudo piano-boot-switch
to-android --reboot` ([device/boot](../boot/README.md)) switches to Android
directly.

## How it works

| File | Role |
|---|---|
| `piano-devmode.service` | Oneshot, `WantedBy=usb-gadget.target` (udev starts that target when the USB device controller appears); `ConditionKernelCommandLine=!piano.debug=1`; pulls `systemd-networkd.service` and the SSH socket |
| `/usr/sbin/piano-devmode check` | Start check: `sshd` present, `ssh-keygen -A` (creates missing host keys, so they exist from the first start), `sshd -t` of the developer-mode configuration |
| `/usr/libexec/piano/devmode-gadget` | configfs gadget `piano-devmode`: one NCM function, `/etc/piano-network` MACs, the debug channel's USB IDs and serial `piano-<androidboot.serialno>`; no console, timer or DHCP daemon. `start` is a no-op when already bound and rebuilds an unbound leftover; `stop` removes the gadget and with it both interfaces |
| `50-piano-devmode.network` | systemd-networkd: matches only the device MAC (and not in debug boots), `192.168.88.2/24`, DHCP server with the single lease `192.168.88.10`, no router, DNS, NTP, SIP or time zone offered; `KeepConfiguration=yes` so networkd does not touch other links' routes or rules. NetworkManager ignores the link (`NM_UNMANAGED` in `71-piano.rules`) |
| `piano-devmode-ssh.socket` | `ListenStream=192.168.88.2:22`, `FreeBind=yes` (listens before the address exists), `Accept=yes`; `BindsTo=piano-devmode.service`, no `[Install]` |
| `piano-devmode-ssh@.service` | `sshd -i -f /usr/lib/piano/devmode/sshd_config` per connection, like OpenSSH's `sshd@.service`; `PartOf=piano-devmode.service`, so `off` ends the sessions |
| `/usr/lib/piano/devmode/sshd_config` | `PermitRootLogin no`, password logins through PAM as in the sshd defaults, `internal-sftp`; the administrator's `/etc/ssh/sshd_config.d/*.conf` are included last and can tighten but not loosen these settings |
| `io.github.piano.devmode.policy` | polkit action for `pkexec /usr/sbin/piano-devmode` |

The network contract is the debug channel's: `initramfs/network.json` is the
source, `/etc/piano-network` is generated from it, and
`tests/test-devmode-files.sh` checks the socket and `.network` literals
against it. The gadget's configfs steps follow `initramfs/usb-diag`; the RAM
debug channel keeps that script.

systemd-networkd is started on demand and stays running when developer mode
is turned off; it manages no other link on the Ubuntu desktop.

## Security

- Anyone holding the other end of the cable can try to log in. The link is a
  private point-to-point network, but there is no further restriction:
  every local account with a password can log in, and so can every account
  with an authorized key.
- Root cannot log in; administrators use `sudo` after logging in.
- Host keys are the system's `/etc/ssh/ssh_host_*_key`, created on the first
  start if missing.
- SSH listens only on `192.168.88.2`, which exists only while developer mode
  runs; it is not reachable over other networks unless Ubuntu's own
  `ssh.socket` or `ssh.service` is also enabled (see above).
- To harden it, put a key in `~/.ssh/authorized_keys` (for example
  `ssh-copy-id USER@192.168.88.2`) and add `PasswordAuthentication no` in
  `/etc/ssh/sshd_config.d/`. To remove the login entirely, run
  `sudo piano-devmode off`.

## Tests

```
sh device/devmode/tests/test-devmode-files.sh [UNIT_DIR [OPENSSH_ROOT]]
python3 tools/test-piano-devmode-ssh.py
sh device/devmode/tests/qemu-gadget-test.sh QEMU IMAGE BUSYBOX OUTDIR dummy_hcd.ko mii.ko usbnet.ko cdc_ether.ko cdc_ncm.ko
```

The first checks the units, network file, OpenSSH configuration, shell
syntax and polkit action; `UNIT_DIR` can be an Ubuntu 26.04 root's unit
directory and `OPENSSH_ROOT` an extracted `openssh-server` package.
`shellcheck` is used when installed. The QEMU test needs a kernel with
configfs and the NCM function built in and a matching `dummy_hcd` module.
