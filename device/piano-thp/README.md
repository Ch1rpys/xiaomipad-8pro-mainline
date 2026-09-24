# Piano THP Finger Processing

This is the offline finger-processing foundation for the NT36532E controller.
It reuses the Apache-2.0 processing core and filters from `xiaomi-sheng-thp`;
source identity and changes are recorded in the repository `NOTICE`.

It is not yet a live input service. The piano SPI transport, uinput integration,
physical axis orientation, real finger gestures and pen support are not validated.
No Android libraries, firmware, electrode calibration or device records are shipped.

The pinned kernel now contains an experimental `nt36532e-thp` misc transport,
with its NTP1 contract and source provenance documented beside the driver.
Firmware parsing and simulated register downloads pass ARM64 KUnit with the
user-supplied piano image; physical SPI and IRQs are untested. Board nodes and
the diagnostic configuration do not enable it. Live reader/uinput integration
is the next step; the current executable below remains an offline replayer.

## Build

Requires a C++20 compiler, Make and the nlohmann JSON development headers
(`nlohmann-json3-dev` on Ubuntu). The tested header version is 3.11.3.

```sh
make
make test
```

`CXX`, `CPPFLAGS`, `LDFLAGS`, `JSON_INCLUDE`, `OUT` and `RUNNER` can be supplied
for cross-compilation and host-side QEMU-user testing. No build step accesses a tablet.
The unit test uses synthetic coordinates to check calibration plumbing and reset;
it does not establish hardware touch support.

## Private Inputs

The vendor configuration is not standard INI. The extraction tool uses a lexer
and literal parser for the required numeric assignments, and does not execute it.
Only separable 40-row/60-column electrode maps with the supported processing
units and symmetric edge parameters are currently accepted.

```sh
python3 ../../tools/extract-thp-calibration.py \
  --input /path/to/own/piano_nova_csot_thp_config.ini \
  --output /path/to/private/calibration.json
build/piano-thp-replay --stock-ring \
  /path/to/private/calibration.json /path/to/private/stock-records.bin
```

Keep both inputs, the extracted calibration and resulting reports private.
The output uses 10 units per pixel; X follows electrode columns and Y follows
rows. These are processor axes, not a verified transformation to panel coordinates.
The filter consumes the same calibrated bounds in its transposed coordinate frame.

The replayer reads the observed 24-byte Android record header and 5192-byte
payload, verifies the firmware header and declared checksum region, then orders
ring slots by sequence. Unsupported packet types, invalid checksum, duplicate
sequences or non-increasing timestamps are errors. Opaque trailing bytes are not
included in the firmware checksum and are not treated as finger matrix data.

The ten available real idle records establish packet decoding and reference
acquisition, not finger tracking. Only one record follows reference acquisition
in that sample; it produces no contacts. Positive gestures, edge calibration,
orientation, timing under load and the remaining upstream filter tuning still
need actual piano input evidence.
