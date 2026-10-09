# SPDX-License-Identifier: BSD-3-Clause
# AudioReach topology of the Xiaomi-Pad-8-Pro sound card (desktop DTB):
# speaker playback on the secondary LPAIF TDM interface and internal-DMIC
# capture on the VA macro. Built against linux-msm/audioreach-topology:
#   m4 -I device/audio -I <audioreach-topology> device/audio/Xiaomi-Pad-8-Pro.m4
# Stream/device structure from its SM8550-HDK.m4 (Copyright, Linaro Ltd, 2023)
# and blu-sharky/debian-piano topology/Xiaomi-Pad-8-Pro.m4 (BSD-3-Clause);
# the capture part is device/audio/Piano-Capture-Diag.m4 unchanged.
include(`audioreach/audioreach.m4')
include(`audioreach/stream-subgraph.m4')
include(`audioreach/device-subgraph.m4')
include(`util/route.m4')
include(`util/mixer.m4')
include(`audioreach/tokens.m4')

# MultiMedia1 playback, one to four channels. No DSP volume module: the
# upstream one goes to +18 dB (65535 with unity at 8192); the gain stays in the
# amplifiers, which the machine driver caps.
STREAM_SG_PCM_ADD(audioreach/subgraph-stream-playback.m4, FRONTEND_DAI_MULTIMEDIA1,
    `S16_LE', 48000, 48000, 1, 4,
    0x00004001, 0x00004001, 0x00006001, `110000')

# MultiMedia3 capture; q6apm's capture frontend requires at least two channels.
STREAM_SG_PCM_ADD(audioreach/subgraph-stream-capture.m4, FRONTEND_DAI_MULTIMEDIA3,
    `S16_LE', 48000, 48000, 2, 2,
    0x00004003, 0x00004003, 0x00006020, `110000')

# Speakers: four FS19xx amplifiers on the secondary LPAIF TDM interface, as
# stock runs it: 48 kHz, 4 x 32-bit slots, all four active (ODM
# backend_conf.xml TDM-LPAIF-RX-SECONDARY ... slot_mask="15"). The ODM ACDB
# carries PARAM_ID_TDM_INTF_CFG for LPAIF interface 1 with sync source
# internal, data out enabled, mask 0xf, 4 slots, width 32, data delay 1 and no
# sync inversion; of its two such entries one has sync mode 1 (long) and one 0
# (short), and which belongs to playback is not decoded. Long sync is taken, as
# debian-piano did; this is the first value to revisit if the amplifiers report
# clock or frame errors.
define(`TDM_SYNC_SRC', `1') dnl internal
define(`TDM_DATA_OUT_ENABLE', `1') dnl
define(`TDM_SLOT_MASK', `0xF') dnl
define(`TDM_NSLOTS', `4') dnl
define(`TDM_SLOT_WIDTH', `32') dnl
define(`TDM_SYNC_MODE', `1') dnl long
define(`TDM_INVERT_SYNC', `0') dnl
define(`TDM_DATA_DELAY', `1') dnl
DEVICE_SG_ADD(piano/subgraph-device-tdm-playback.m4, `Secondary TDM0', SECONDARY_TDM_RX_0,
    `S32_LE', 48000, 48000, 4, 4,
    LPAIF_INTF_TYPE_LPAIF, 1, 0, DATA_FORMAT_FIXED_POINT,
    0x00004005, 0x00004005, 0x00006050, `SECONDARY_TDM_RX_0')

# VA codec DMA TX0, as in Piano-Capture-Diag.m4.
DEVICE_SG_ADD(audioreach/subgraph-device-codec-dma-capture.m4, `VA_CODEC_DMA_TX_0', VA_CODEC_DMA_TX_0,
    `S16_LE', 48000, 48000, 2, 2,
    LPAIF_INTF_TYPE_VA, CODEC_INTF_IDX_TX0, 0, DATA_FORMAT_FIXED_POINT,
    0x00004008, 0x00004008, 0x00006080)

STREAM_DEVICE_PLAYBACK_MIXER(SECONDARY_TDM_RX_0, ``SECONDARY_TDM_RX_0'', ``MultiMedia1'')
STREAM_DEVICE_PLAYBACK_ROUTE(SECONDARY_TDM_RX_0, ``SECONDARY_TDM_RX_0 Audio Mixer'', ``MultiMedia1, stream0.logger1'')

STREAM_DEVICE_CAPTURE_MIXER(FRONTEND_DAI_MULTIMEDIA3, ``VA_CODEC_DMA_TX_0'')
STREAM_DEVICE_CAPTURE_ROUTE(FRONTEND_DAI_MULTIMEDIA3, ``MultiMedia3 Mixer'', ``VA_CODEC_DMA_TX_0, device110.logger1'')
