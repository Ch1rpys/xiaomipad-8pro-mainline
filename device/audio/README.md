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
No such card or boot candidate is enabled yet. Do not install this graph as a
replacement for an unrelated sound card. The output is topology data, independent
of CPU architecture, distribution and desktop; native packaging remains separate.

Hardware preparation still requires ADSP/GPR/q6prm, the VA fsgen clock provider,
TX macro, piano LPI GPIO12/13 pin control, and a codec-only DAI path with correct
channel/lifecycle handling. The current shared machine driver invokes SoundWire
helpers for TX3; its behavior without a SoundWire codec needs review. Topology
compilation cannot settle it. Do not add a dummy SoundWire device to force probe.

Real capture must establish the effective mixer controls, DMIC/decimator mapping,
clock/power behavior, audible speech and reopening. Add UCM after those controls
are proven, then use standard ALSA/PipeWire interfaces. No volume defaults, mic
calibration, sensor matrices, proprietary firmware or installed service are here.
The upstream BSD-3-Clause macros remain at their source; see `NOTICE` and
`LICENSES/audioreach-BSD-3-Clause.txt` for the derivative graph's license.
