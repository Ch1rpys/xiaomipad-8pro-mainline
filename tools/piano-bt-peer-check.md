# Bluetooth peer acceptance

Run `piano-bt-peer-check.py` on a Linux host with an unused Bluetooth adapter.
It uses that adapter as the peer of an already running piano over SSH. It does
not boot the tablet, install packages, replace kernels, or restart its desktop.

Prerequisites:

- A working, known SSH host key and the expected tablet boot serial.
- Both machines: BlueZ (`l2ping`, `hcitool`), `bluez-obexd`, PipeWire tools,
  WirePlumber, Python 3 with `dbus` and `gi`. The tablet's `pw-play` must support
  `--raw` (tested with PipeWire 1.6). Host analysis also uses NumPy.
- Host: noninteractive sudo for the read-only HCI/kernel checks. Tablet: sudo
  through an existing private password file, or noninteractive sudo. The script
  reads the password into memory and sends it only through sudo's stdin.
- Neither machine may already know the test peer. The host must have no active
  audio streams when its temporary WirePlumber rule is installed. Existing
  OBEX sessions and discovery sessions are refused.

```sh
/usr/bin/python3 tools/piano-bt-peer-check.py \
  --ssh '<USER>@<TABLET_USB_IP>' --serial '<SERIAL>' \
  --sudo-password-file '<EXISTING_PRIVATE_TMPFS_FILE>' \
  --output '<NEW_PRIVATE_EVIDENCE_DIRECTORY>'
```

The output directory must be new. It has mode 0700 and contains addresses,
pairing records, logs, payloads and recordings: **never commit or publish it**.
Each completed item prints one JSON line with PASS/FAIL and its evidence path.
`results.json` contains the details; the exit status is nonzero if any item
fails. `runner.py` and `inputs.json` bind a run to the exact script bytes.
For a focused audio investigation, `--skip-obex` omits file transfers and emits
no OBEX verdict; the default always runs the full sequence.
`--reconnect-only` omits both OBEX and audio but retains initial pairing and
bidirectional pings before and after disconnect. `--reconnect-from host` selects
the host as the initiator of the single reconnection (default: tablet). Both
peers must already be bonded before this step; automatic fresh pairing after
a failed setup must not be reported as successful reconnection.
`--reconnect-count 2` or `3` captures a bounded intermittent failure after one
pairing. Every cycle is reported separately; the first failed cycle stops the
sequence without retrying it. The default remains one cycle.

The sequence is power/discoverability, BR/EDR discovery, tablet-initiated
NoInputNoOutput pairing, trust/connect, five l2ping packets in each direction,
RSSI, two independent random 1 MiB OBEX Object Push transfers with SHA-256
comparison, A2DP, disconnect/reconnect without Pair(), and another five pings.
Inquiry RSSI is in dBm; `hcitool rssi` reports the controller's link RSSI value,
which must not be presented as an absolute dBm measurement.

For A2DP, the host temporarily advertises only the sink role. Its peer-specific
WirePlumber rule exposes the decoded Bluetooth stream as a recording input.
There is no speaker or microphone loopback. The tablet sends silence until the
host's dynamic receive node and recorder are running, then one second of
silence, ten seconds of 1 kHz at amplitude 0.25, and another second of silence.
The host checks the tone duration, a 990–1010 Hz FFT peak and at least 20 dB
above the recorded silence noise floor. The S16 quantization floor prevents
reporting infinite SNR for digital zero. Node codec names and BlueZ transport
configuration bytes are retained in `a2dp-progress.json`/`results.json`.

The temporary BlueZ agents accept only the specified peer. The original agents
stay registered; unregistering the temporary default agent restores BlueZ's
previous default-agent queue. OBEX runs as the normal user on a private D-Bus
session using the distribution's obexd and its `opp,bluetooth,filesystem`
plugins. The existing user OBEX unit is temporarily masked/stopped to avoid
competing registrations or desktop authorization dialogs, then restored.

Cleanup runs on normal exit, exception, stdin EOF or SIGTERM. Endpoint processes
also have a 15 minute deadline. Cleanup removes the new bond on both sides,
stops playback/recording/OBEX, unregisters the test agents, restores adapter
properties and the user OBEX unit, removes the temporary host rule, and restarts
only the host's WirePlumber. Before/after receipts compare adapter settings and
advertised UUIDs, existing bonds, audio defaults/profiles/volumes, service state,
boot ID and the keyboard monitor PID/start time. A failed restoration remains
FAIL; the tablet's temporary directory is retained for recovery and its path
is recorded. No automatic reboot, controller reset or pairing retry is used.
If the host's WirePlumber restart reapplies a different saved mixer volume,
cleanup explicitly restores the original host node volumes and mute state.

A PASS measures this host/tablet pair and this running boot. It does not certify
GNOME's interactive pairing UI, cold boot, suspend, range, Wi-Fi under load,
headset acoustics, HFP calling, HID accessories or other codecs.

The lifecycle follows the upstream [BlueZ Agent API](https://github.com/bluez/bluez/blob/5.72/doc/agent-api.txt),
[OBEX API](https://github.com/bluez/bluez/blob/5.72/doc/obex-api.txt), and
[PipeWire BlueZ device implementation](https://github.com/PipeWire/pipewire/blob/1.0.5/spa/plugins/bluez5/bluez5-device.c).
The latter names the receiving profile `audio-gateway` and creates incoming
A2DP nodes only when the transport becomes pending.
In PipeWire 1.0, `bluez5.media-source-role=input` must reach the
[media-source node](https://github.com/PipeWire/pipewire/blob/1.0.5/spa/plugins/bluez5/media-source.c),
not just the card; the SPA node publishes its own media class and driver flag.
