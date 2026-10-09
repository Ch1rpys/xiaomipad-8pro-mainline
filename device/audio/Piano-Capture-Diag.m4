# SPDX-License-Identifier: BSD-3-Clause
# Capture graph derived from linux-msm/audioreach-topology SM8550-HDK.m4.
# Copyright, Linaro Ltd, 2023
# Piano reduction: internal DMICs on the VA macro, one two-channel capture PCM.
include(`audioreach/audioreach.m4')
include(`audioreach/stream-subgraph.m4')
include(`audioreach/device-subgraph.m4')
include(`util/route.m4')
include(`util/mixer.m4')
include(`audioreach/tokens.m4')

# Stream IDs are graph-local upstream conventions, not board calibration.
# q6apm's capture frontend requires at least two channels.
STREAM_SG_PCM_ADD(audioreach/subgraph-stream-capture.m4, FRONTEND_DAI_MULTIMEDIA3,
    `S16_LE', 48000, 48000, 2, 2,
    0x00004003, 0x00004003, 0x00006020, `110000')

# VA codec DMA TX0, as in the upstream graph. Which DMIC feeds which VA
# decimator is a codec mixer choice (UCM). AudioReach builds a contiguous DMA
# mask from channel 0, so two channels carry VA DEC0 and DEC1.
DEVICE_SG_ADD(audioreach/subgraph-device-codec-dma-capture.m4, `VA_CODEC_DMA_TX_0', VA_CODEC_DMA_TX_0,
    `S16_LE', 48000, 48000, 2, 2,
    LPAIF_INTF_TYPE_VA, CODEC_INTF_IDX_TX0, 0, DATA_FORMAT_FIXED_POINT,
    0x00004008, 0x00004008, 0x00006080)

STREAM_DEVICE_CAPTURE_MIXER(FRONTEND_DAI_MULTIMEDIA3, ``VA_CODEC_DMA_TX_0'')
STREAM_DEVICE_CAPTURE_ROUTE(FRONTEND_DAI_MULTIMEDIA3, ``MultiMedia3 Mixer'', ``VA_CODEC_DMA_TX_0, device110.logger1'')
