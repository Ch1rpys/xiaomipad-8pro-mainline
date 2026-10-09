# Piano internal-microphone capture: topology and UCM

This directory holds the single capture graph (`Piano-Capture-Diag.m4`) and the
UCM profile (`ucm2/`) for the `Piano-Capture-Diag` sound card that the desktop
DTB declares. Capture uses the LPASS VA macro: `VA_CODEC_DMA_TX_0` feeds the
MultiMedia3 front end (PCM device 2), 48 kHz, S16_LE, two channels. There is no
playback; the speaker amplifiers are not enabled. Nothing here has recorded on
the tablet yet.

## Why the VA macro

From the saved stock piano build (OS3.0.303.0.WPYCNXM):

- The stock machine node routes every `Digital MicN` to both `TX DMICn` and
  `VA DMICn`, and the vendor `lpass_cdc_dmic_clk_enable()` programs the VA
  `DMICx_CTL` clock for TX and VA alike. The DMIC lines are shared; the macro is
  a routing choice, not wiring.
- All four DMIC pin pairs are enabled: LPI GPIO6/7 (DMIC0/1), 8/9 (DMIC2/3),
  12/13 (DMIC4/5) and 17/18 (DMIC6/7), 4 mA. The ODM mixer overlay uses one
  microphone per pair: DMIC0 side-top, DMIC2 side-bottom, DMIC4 top, DMIC6 back.
- Android records ordinary audio on TX (`CODEC_DMA-LPAIF_RXTX-TX-3`) and uses
  VA (`CODEC_DMA-LPAIF_VA-TX-0`) for voice activation. Its default handset
  recording pairs DMIC0 and DMIC2; its VA dual-microphone path is
  DEC0 <- DMIC0, DEC1 <- DMIC2.
- Both macros use DMIC clock divider 4 at 48 kHz (TX by its DT factor; VA's 16
  is switched to 4 above 16 kHz in the vendor `hw_params`).

On mainline, the VA path owns the DMIC clock itself, as on the upstream SM8750
MTP, while the TX DMIC inputs have no clock event and needed the VA macro as an
auxiliary device. The VA route therefore takes the same microphones and clock
divider as stock with the upstream driver structure. It differs from Android's
normal-recording backend (TX3); that route stays available in Git history
(topology `2727c427...`) if VA fails on the tablet.

The matching DT change is kernel commit `062a6c01d647` on branch
`piano/mic-va-20261010`: a VA dai-link, the four DMIC pin pairs on the VA macro
at 4 mA and `qcom,dmic-sample-rate = <2400000>` (9.6 MHz / 4). **This topology
and UCM require that DTB.** Desktop DTBs from earlier kernels and the
`piano/diag` mic-diag DTB use TX3 and pair only with the earlier graph; do not
ship one without the other.

## UCM

`ucm2/` follows the alsa-ucm-conf layout: `conf.d/sm8750/Piano-Capture-Diag.conf`
(symlink; driver `sm8750`, card long name `Piano-Capture-Diag`) points to
`Qualcomm/sm8750/Xiaomi-Pad-8-Pro/Piano-Capture-Diag.conf`, which loads
`HiFi.conf`. Install the tree under `/usr/share/alsa/ucm2/` keeping the symlink.
The verb enables the `MultiMedia3 Mixer VA_CODEC_DMA_TX_0` route; the `Mic`
device sets VA DEC0 <- DMIC0 and DEC1 <- DMIC2 (stock `va-mic-dmic`) at gain 100
(+16 dB, the upstream VA DMIC default; stock's 84 = 0 dB is followed by DSP gain
that this graph lacks). DEC mode stays at the driver default; stock
`ADC_LOW_PWR` belongs to voice activation. The mainline VA driver forces a
150 Hz high-pass filter on every stream start.

Checked offline: alsa-lib 1.2.11 `alsaucm` parses the tree (with `${CardId}`
replaced in a temporary copy, since no card exists on the build host) and
reports verb HiFi, device Mic, `CapturePCM hw:0,2`, two channels. All cset
names and values exist in the real piano control readback of P24-03 (VA
controls) or in the decoded topology (the MultiMedia3 route). The sequences
have not run against the card.

## Build

Build against a clean checkout at the commit in `source.json`, using m4 and
alsatplg:

```sh
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

With alsatplg 1.2.9 / libatopology 1.2.11 this gives 5164 bytes, the identity
locked in `diagnostic.json`. The compiler warns that `VA_CODEC_DMA_TX_0 Capture`
is an undefined route source, as it did for TX3 and does for the unmodified
upstream graph; the kernel DAI table declares the stream. Decoding shows one
two-channel 48 kHz capture PCM, the VA device subgraph (interface type VA,
index TX0) and no playback. Recompiling the decoded output fails on tuple
references with this tool version, also for upstream input; no roundtrip is
claimed. The kernel loads `qcom/sm8750/Piano-Capture-Diag-tplg.bin`.

## Recording check

The q6apm capture front end needs two channels, at least 6144 bytes per period
and multiples of 480 frames; a 1920-frame period and 7680-frame buffer satisfy
this. Keep `arecord -v` output and the live `hw_params`.

`tools/mic-capture-check.py` judges a WAV taken on the tablet
(`--print-command` gives the arecord line). Per channel, after the first
0.5 s: not silent or constant, not clipped, AC level at least -60 dBFS, and a
non-flat spectrum (Welch spectral flatness below 0.8 over 50 Hz to 8 kHz).
Narrow lines, mains-related or not, are warnings. `path_alive` reports live
data separately from the verdict. A quiet room can leave a working microphone
below -60 dBFS (FAIL with `path_alive`), and ambient sound cannot prove the
signal is acoustic: clock leakage or interference can be non-flat. `--tone HZ`
checks a known source. Audibility of speech needs a person.

`diagnostic.json` keeps the explicit RAM-probe module order, excluded
consumers and the compiled topology identity used by `build-boot.py` and
`build-firmware-deb.py`. The P23/P24 hardware probe results remain those of the
earlier TX3 graph.

The upstream BSD-3-Clause macros are consumed from their pinned checkout. See
`NOTICE`, `LICENSES/audioreach-BSD-3-Clause.txt`, `LICENSES/debian-piano-MIT.txt`
and `LICENSES/alsa-ucm-conf-BSD-3-Clause.txt`.
