# Piano audio: topology and UCM

This directory holds the AudioReach topologies and the UCM profile (`ucm2/`) of
the piano sound card that the desktop DTB declares.

- `Xiaomi-Pad-8-Pro.m4` (with `piano/`): the card `Xiaomi-Pad-8-Pro` of kernel
  branch `piano/speakers-20261010`: speaker playback on MultiMedia1 (PCM 0) to
  the secondary LPAIF TDM interface, and the VA microphone capture below on
  MultiMedia3 (PCM 2). Identity in `card.json`. Nothing here has played on the
  tablet yet.
- `Piano-Capture-Diag.m4`: the capture-only card `Piano-Capture-Diag` of
  7.2.6-piano5 and earlier desktop DTBs (identity in `diagnostic.json`, shipped
  by firmware 0.3). The UCM tree no longer names that card.

## Speakers

Four FourSemi FS19xx amplifiers (I2C hub 0, 0x34-0x37) share the secondary TDM
interface, as stock Android runs it: backend `TDM-LPAIF-RX-SECONDARY`, 48 kHz,
four 32-bit slots, all active, bit clock 6.144 MHz from the SoC. Each amplifier
takes its slot from the vendor preset (`fs19xx.fsm`, loaded by the kernel
driver): slot 0 top left, 1 top right, 2 bottom left, 3 bottom right in
landscape with the front camera on top (the bottom pair is still to be
confirmed by ear). SM8750 has no Audio IF block; the stock ACDB uses the LPAIF
TDM sink module (0x0700100E), so `piano/module_tdm.m4` describes that module
with the upstream token numbers 262-269. The interface values are those of
the stock ACDB `PARAM_ID_TDM_INTF_CFG` for LPAIF interface 1: internal sync,
data out enabled, mask 0xf, 4 slots, width 32, data delay 1, no sync
inversion. The ACDB holds two such entries that differ only in sync mode; which
one is playback is not decoded, and long sync (1) is used, as debian-piano
did.

The playback stream subgraph is `piano/subgraph-stream-playback.m4`, a copy of the unused
upstream `audioreach/subgraph-stream-playback.m4` with the WR_SH output port set to 1. Upstream
passes 0 there, so the kernel's topology loader (it keeps a link only when source port,
destination instance and destination port are all non-zero) gives the DSP a WR_SH that is not
connected to the PCM decoder; on piano (speakers-1, 2026-10-10) the ADSP rejected
APM_CMD_GRAPH_OPEN of that graph with error 1 before any TDM, clock or amplifier step. The
vol-playback variant every upstream board uses has port 1. `tools/check-audioreach-tplg.py`
reports such dropped links from the compiled binary.

The playback stream graph has no DSP volume module (the upstream one reaches
+18 dB). Gain lives in the amplifiers: the kernel card caps each `<position>
Amp Volume` at 215 of 255 (0.375 dB steps, -15 dB) because no speaker
protection runs, and the UCM `Speaker` device sets 192 (-23.6 dB). Software
volume therefore ends at digital full scale. Stock Android uses 243/235 with
its DSP protection on the TDM feedback port, which is not described here.

Unattended checks use `tools/speaker-playback-check.py tone` (1 kHz, at most
-20 dBFS, 3 s, four channels) and `tools/speaker-playback-device.sh` on the
tablet: amplifiers at 160 (-35.6 dB), raw `hw:CARD,0`, a 5 s watchdog that
stops the stream and, if the PCM stays open, unbinds the amplifiers (their
reset lines then hold them in shutdown). `speaker-playback-check.py judge`
checks DEVID 0x2900 on all four, the volume limits, the stream, kernel log
errors, the amplifier power state during and after the tone, STATUS equality
across the four amplifiers, and a battery-current proxy. A PASS is not an
audibility result.

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

`ucm2/` follows the alsa-ucm-conf layout: `conf.d/sm8750/Xiaomi-Pad-8-Pro.conf`
(symlink; driver `sm8750`, card long name `Xiaomi-Pad-8-Pro`) points to
`Qualcomm/sm8750/Xiaomi-Pad-8-Pro/Xiaomi-Pad-8-Pro.conf`, which loads
`HiFi.conf`. Install the tree under `/usr/share/alsa/ucm2/` keeping the symlink.
The verb enables the `SECONDARY_TDM_RX_0 Audio Mixer MultiMedia1` and
`MultiMedia3 Mixer VA_CODEC_DMA_TX_0` routes. The `Speaker` device (PCM 0,
four channels) sets the four amplifier gains to 192 and exposes no hardware
volume. The `Mic`
device sets VA DEC0 <- DMIC0 and DEC1 <- DMIC2 (stock `va-mic-dmic`) at gain 100
(+16 dB, the upstream VA DMIC default; stock's 84 = 0 dB is followed by DSP gain
that this graph lacks). DEC mode stays at the driver default; stock
`ADC_LOW_PWR` belongs to voice activation. The mainline VA driver forces a
150 Hz high-pass filter on every stream start.

Checked offline: alsa-lib 1.2.11 `alsaucm` parses the tree (with `${CardId}`
replaced in a temporary copy, since no card exists on the build host) and
reports verb HiFi, devices Speaker (`PlaybackPCM hw:0,0`, four channels) and
Mic (`CapturePCM hw:0,2`, two channels). The speaker control names are the
kernel's (`SECONDARY_TDM_RX_0 Audio Mixer MultiMedia1` in the decoded
topology; `<sound-name-prefix> Amp Volume` from the FS19xx driver) and have not
been read back from a card. All cset
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

The card topology builds the same way:

```sh
m4 -I device/audio -I "$AUDIOREACH_SOURCE" device/audio/Xiaomi-Pad-8-Pro.m4 > out/audio/Xiaomi-Pad-8-Pro.conf
alsatplg -c out/audio/Xiaomi-Pad-8-Pro.conf -o out/audio/Xiaomi-Pad-8-Pro-tplg.bin
```

giving 10172 bytes (`card.json`, `e5d96904…`; the first build `ab5b40c5…` had the WR_SH port 0), with the same warning for `VA_CODEC_DMA_TX_0
Capture` and one for `Secondary TDM0 Playback`, the stream name of the
kernel's SECONDARY_TDM_RX_0 DAI. The decoded TDM sink tuples carry module
0x0700100E, interface type 0 index 1 and tokens 262-269 = 1, 1, 15, 4, 32, 1,
0, 1. The kernel loads `qcom/sm8750/Xiaomi-Pad-8-Pro-tplg.bin`.

`python3 tools/check-audioreach-tplg.py out/audio/Xiaomi-Pad-8-Pro-tplg.bin` then lists the
ten in-subgraph links and no error; the first build fails it (`link-dropped` on
`stream0.wrsh_ep1`), while `Piano-Capture-Diag` `fc92bb08…` (accepted on piano) and upstream
SM8550-HDK, GLYMUR-CRD and LEMANS-EVK pass.

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
