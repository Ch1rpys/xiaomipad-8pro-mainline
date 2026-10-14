# Display and night-light acceptance

Run `piano-display-mode-check.py` as root **on Piano**, from SSH during a
recoverable RAM session. `--serial` and `--kernel` must match the target; the
output directory must be new. Results include private session/device data.
No hardware driver is loaded, unloaded or rebound.

```sh
python3 /run/piano-display-mode-check.py \
  --serial "$PIANO_SERIAL" --kernel 7.2.10-piano23 \
  --label piano23-modes --output /var/tmp/piano23-modes

python3 /run/piano-display-mode-check.py \
  --serial "$PIANO_SERIAL" --kernel 7.2.10-piano23 \
  --crc-source encoder --nightlight 50 \
  --label piano23-nightlight --output /var/tmp/piano23-nightlight
```

Without `--nightlight`, the original 60/120/90/144/120 Hz and DPMS sequence is
unchanged. `--crc-source encoder` is also accepted for this sequence; both
physical encoder CRC columns must change with the moving pointer.

With `--nightlight N`, the current mode, scale, transform and DPMS are never
written. Use one unlocked GNOME Wayland session, just DSI-1, and a **static
fullscreen colored image**. Hide clocks, blinking carets and animations; leave
physical input idle. The tool parks its virtual pointer once before sampling.
It does not create a fullscreen application or suppress notifications. Scene
changes fail the constant-endpoint/baseline checks and must not be called a
REGDMA failure solely from that result. Make sure colord has an assigned
profile first (the separate `piano-panel-srgb.service` integration provides the
distribution sRGB profile only for an otherwise unconfigured panel).

The five settings in `org.gnome.settings-daemon.plugins.color` are captured as
both effective values and explicit user values. The test selects a manual
12-hour window centered on the current local time, a fixed 4000 K temperature,
and alternates enabled/disabled. It waits for GSD's reported active/temperature
endpoint (up to 15 seconds; GSD 50.1 smooths a transition over 5 seconds), then
waits at least 2 seconds and samples for 3 seconds by default. A baseline OFF
sample precedes the N ON/OFF pairs. Fifty cycles need roughly 17 minutes plus
startup/restoration; provide enough RAM-session time.

Every endpoint must have two constant encoder CRC values, advancing frame
numbers at the current refresh rate within 15%, no new kernel errors including
REGDMA faults/timeouts, and the same GNOME Shell PID and D-Bus owner. Every ON
CRC tuple must differ from the OFF baseline; every OFF tuple must equal that
same baseline. Only a complete sequence with successful restoration can PASS.
No LM fallback is permitted for night light: LM's tap is before GC. Missing CRC
support is INCOMPLETE. Encoder CRC validates the digital pipeline, not physical
panel emission or color accuracy.

`finally` restores all five GSettings, using `reset` for originally unset keys,
checks readback, and includes the restored GSD transition in the log window.
SIGINT/SIGTERM/SIGHUP trigger this cleanup; SIGKILL, power loss or a kernel
D-state hang cannot be recovered by user-space cleanup. A paused-until-tomorrow
night-light state is preserved and reported INCOMPLETE. No MMIO, `/dev/mem`,
driver debug bits, calibration file or persistent monitor configuration is used.

`result.json`, per-step JSON, `kernel-log.json` and `commands.jsonl` retain the
observations. Exit codes: **0 PASS**, **1 FAIL**, **2 INCOMPLETE**. Offline checks:

```sh
python3 -m py_compile tools/piano-display-mode-check.py
python3 tools/tests/test-display-mode-check.py
```

These check parsers/criteria only, not real display operation.
