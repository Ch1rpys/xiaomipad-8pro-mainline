# Iris RAM decode diagnostic

`iris-check.sh --bundle DIR --output /run/iris-result` runs one bounded test as root.
Prepare the fixed 5 s, 1920×1080, 30 fps H.264 clip and host software frame-MD5
reference in the local RAM test bundle. `clip.json` pins every input, including
the locked `firmware/qcom/sm8750/vpu35_4v.mbn`; the firmware manifest and
`tools/firmware_payload.py` remain authoritative for staging firmware.

On the installed Ubuntu root, install these before the RAM test:

```sh
sudo apt-get install python3 kmod v4l-utils gstreamer1.0-tools \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad
```

The test requires a debug RAM boot matching the kernel release enforced by
[`iris-check.py`](iris-check.py) and starts before uptime 420 s, leaving room
for its 120 s total budget and the 600 s return timer.
It selects the `qcom-iris-decoder` node with `qcom,sm8750-iris` DT identity,
prints both V4L2 format queues, and uses only `v4l2h264dec device=...`.
It sets a fresh RAM GStreamer registry so hardware elements are probed for
this boot, then compares all 150 packed I420 frames against the host decode.
There is no software fallback. `IRIS_RESULT=PASS/FAIL/UNAVAILABLE` explains
the result; PASS requires exact frame-MD5 equality and count, not just EOS.
Each actual frame MD5 is printed for collection before the RAM boot exits.
Logs and raw output require 600 MB free in `/run`.

The Iris initrd purpose preserves its hash-verified VPU firmware in `/run` and
sets the standard loader path before switch-root, so early root services can
open Iris too. After switch-root, the check copies the same
locked blob to its `/run` output and temporarily sets the standard
`firmware_class.path` parameter before opening the device. The prior parameter
is restored even on failure. It does not install firmware on the disk root.
The dmesg excerpt includes Iris/Venus/HFI/firmware messages. A missing success
message alone is not a firmware failure: this driver need not log a successful
load. Successful hardware output is the end-to-end evidence.

The secondary `nvram@7200` node has `read-only` and no cells. Its DT range is
128 bytes; the upstream driver obtains the exported size from SDAM_SIZE.
It rejects offsets below 0x40, and nvmem core clips reads at the exported size.
The script therefore dumps only the available region starting at 0x40 (64
bytes if exported size is 128), and reports its exact bounds. This is a
read-only diagnostic, not an RTC offset interpretation or an RTC write test.
