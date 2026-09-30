# SPDX-License-Identifier: BSD-3-Clause
# Capture graph derived from linux-msm/audioreach-topology SM8550-HDK.m4.
# Copyright, Linaro Ltd, 2023
# Piano diagnostic reduction: one physical DMIC, two-channel capture PCM.
include(`audioreach/audioreach.m4')
include(`audioreach/stream-subgraph.m4')
include(`audioreach/device-subgraph.m4')
include(`util/route.m4')
include(`util/mixer.m4')
include(`audioreach/tokens.m4')

# Stream IDs are graph-local upstream conventions, not board calibration.
STREAM_SG_PCM_ADD(audioreach/subgraph-stream-capture.m4, FRONTEND_DAI_MULTIMEDIA3,
    `S16_LE', 48000, 48000, 2, 2,
    0x00004003, 0x00004003, 0x00006020, `110000')

# The stock sun DAI link maps TX CDC DMA TX3 to tx_macro_tx1.
# DMIC choice/decimator/pin control belongs to the codec and board integration.
# q6apm's capture frontend requires at least two channels. Use DEC0 for the
# single DMIC: AudioReach constructs a contiguous DMA mask starting at channel 0.
DEVICE_SG_ADD(audioreach/subgraph-device-codec-dma-capture.m4, `TX_CODEC_DMA_TX_3', TX_CODEC_DMA_TX_3,
    `S16_LE', 48000, 48000, 2, 2,
    LPAIF_INTF_TYPE_RXTX, CODEC_INTF_IDX_TX3, 0, DATA_FORMAT_FIXED_POINT,
    0x00004009, 0x00004009, 0x00006090)

STREAM_DEVICE_CAPTURE_MIXER(FRONTEND_DAI_MULTIMEDIA3, ``TX_CODEC_DMA_TX_3'')
STREAM_DEVICE_CAPTURE_ROUTE(FRONTEND_DAI_MULTIMEDIA3, ``MultiMedia3 Mixer'', ``TX_CODEC_DMA_TX_3, device120.logger1'')
