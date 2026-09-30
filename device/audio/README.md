# Piano capture diagnostic topology

This is a small board graph using upstream AudioReach macros. It has one mono
48 kHz S16_LE capture stream (MultiMedia3) and the TX_CODEC_DMA_TX_3 backend.
The stock sun machine source maps that backend to tx_macro_tx1; the saved piano
ODM override selects DMIC4 through DEC2 for the main microphone. These are source
and stock configuration facts, not successful Linux recording.

Build against a clean independent checkout at the exact commit in `source.json`.
Use existing m4 and alsatplg; no program here accesses audio or tablet devices:

```sh
# Run from this integration repository; check out source.json's exact commit first.
set -eu
AUDIOREACH_SOURCE=/path/to/audioreach-topology
expected=$(python3 -c 'import json; print(json.load(open("device/audio/source.json"))["commit"])')
test "$(git -C "$AUDIOREACH_SOURCE" rev-parse HEAD)" = "$expected"
test -z "$(git -C "$AUDIOREACH_SOURCE" status --porcelain)"
mkdir -p out/audio
m4 -I "$AUDIOREACH_SOURCE" device/audio/Piano-Capture-Diag.m4 > out/audio/Piano-Capture-Diag.conf
alsatplg -c out/audio/Piano-Capture-Diag.conf -o out/audio/Piano-Capture-Diag-tplg.bin
alsatplg -d out/audio/Piano-Capture-Diag-tplg.bin -o out/audio/decoded.conf
```

Compile and decode completed with alsatplg 1.2.9 / libatopology 1.2.11. The tool
warns that `TX_CODEC_DMA_TX_3 Capture` is an undefined route source; the unmodified
upstream graph has the same warning, and the kernel DAI table declares this name.
Runtime graph binding remains untested. Recompiling the decoded output fails on
tuple references with this tool version, also for unmodified upstream input;
roundtrip equality is not claimed. No integrity check was disabled.

The conventional loader path would be
`qcom/sm8750/Piano-Capture-Diag-tplg.bin` for a card with that model name.
The kernel now has an isolated `sm8750-xiaomi-piano-mic-diag.dtb` with that card
name. The paired 60-second NCM probe can now be packaged with its exact firmware and module inputs. Do not install this graph as a replacement
for an unrelated sound card. The output is topology data, independent
of CPU architecture, distribution and desktop; native packaging remains separate.

The diagnostic DTS connects TX3 to the TX macro, selects the saved piano LPI
GPIO12/13 settings at 4 mA, and adds the VA macro through standard ASoC `aux-devs`.
`TX DMIC4 <- VA DMIC4` and `VA DMIC4 <- VA_MCLK` reuse VA's existing shared clock
control. Its 2.4 MHz setting matches the stock TX divisor of 4 from a 9.6 MHz
source. There is no second VA register owner in the TX driver.

A direct-DMIC stream leak in the shared SoundWire helper is fixed in the kernel;
its five ARM64 KUnit tests pass. A generic ASoC DAPM test confirms clock/gate order
and closing/reopening for this routing shape. It uses synthetic widgets, and does
not test real codec probing, aux-device registration, MMIO or DSP traffic.

`tools/stage-kernel-modules.py` can stage the explicit audio dependency closure;
this is independent of Debian packaging. The audio set has been loaded by BusyBox
modprobe in QEMU with its matching Image. It contains no PMIC GLINK, battmgr or
FastRPC module. Physical ADSP/GPR/APM operation and runtime routing are untested.
`diagnostic.json` fixes the explicit module order, excluded consumers and compiled
topology identity. The boot packager requires the exact 56 DSP firmware files,
this topology, matching module bytes and modular PAS/APR/card drivers. The runner
requires `--load-modules`, captures a baseline first, then loads once in order and
collects module/ALSA/remoteproc state. Its original 60-second PID1 timer remains.
The resulting P24 is an offline probe candidate, not an audio recording result.
The existing ADSP-only P23 remains the first supervised hardware step.

Real capture must establish the effective mixer controls, DMIC/decimator mapping,
clock/power behavior, audible speech and reopening. Add UCM after those controls
are proven, then use standard ALSA/PipeWire interfaces. No volume defaults, mic
calibration, sensor matrices, proprietary firmware or installed service are here.
The upstream BSD-3-Clause macros remain at their source; see `NOTICE` and
`LICENSES/audioreach-BSD-3-Clause.txt` for the derivative graph's license.
