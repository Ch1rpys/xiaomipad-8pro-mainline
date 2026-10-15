/* SPDX-License-Identifier: MIT */
/* Local loopback publication conversion, independent of ISP/control code. */
#ifndef PIANO_NV12_BGRX_H
#define PIANO_NV12_BGRX_H

#include <stddef.h>
#include <stdint.h>

static inline uint8_t bgrx_clip(int v)
{
	return v < 0 ? 0 : v > 255 ? 255 : v;
}

static inline void bgrx_pair(const uint8_t *restrict luma, const uint8_t *restrict chroma,
			     uint8_t *restrict d)
{
	int u = (int)chroma[0] - 128;
	int v = (int)chroma[1] - 128;
	int b = 454 * u, g = -88 * u - 183 * v, r = 359 * v;

	int y0 = (int)luma[0] * 256 + 128;
	int y1 = (int)luma[1] * 256 + 128;
	d[0] = bgrx_clip((y0 + b) >> 8);
	d[1] = bgrx_clip((y0 + g) >> 8);
	d[2] = bgrx_clip((y0 + r) >> 8);
	d[3] = 0;
	d[4] = bgrx_clip((y1 + b) >> 8);
	d[5] = bgrx_clip((y1 + g) >> 8);
	d[6] = bgrx_clip((y1 + r) >> 8);
	d[7] = 0;
}

/* Full-range BT.601, Q8 coefficients; even dimensions, shared Y/UV stride.
 * Destination is tightly packed B,G,R,x bytes (V4L2 XBGR32 / XR24).
 * Input and destination must not overlap; x is deterministic zero padding.
 */
static inline void nv12_to_bgrx(const uint8_t *restrict y,
			      const uint8_t *restrict uv, unsigned int stride,
			      uint8_t *restrict dst, unsigned int w, unsigned int h)
{
	for (unsigned int row = 0; row < h; row++) {
		const uint8_t *luma = y + (size_t)row * stride;
		const uint8_t *chroma = uv + (size_t)(row / 2) * stride;
		uint8_t *d = dst + (size_t)row * w * 4;

		for (size_t col = 0; col < w; col += 2)
			bgrx_pair(luma + col, chroma + col, d + 4 * col);
	}
}

#endif
