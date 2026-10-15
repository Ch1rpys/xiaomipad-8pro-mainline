/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "nv12-bgrx.h"

static int reference(double v)
{
	return v < 0 ? 0 : v > 255 ? 255 : (int)lround(v);
}

static void check(unsigned int stride)
{
	/* Eight 2x2 chroma blocks: neutral, primaries, extremes and mixed colour.
	 * Independent floating-point BT.601 oracle also checks full-range luma.
	 */
	static const uint8_t ys[32] = {
		0, 255, 76, 100, 150, 180, 29, 60,
		16, 235, 50, 200, 20, 240, 90, 128,
		0, 255, 0, 255, 64, 192, 100, 200,
		32, 224, 16, 235, 80, 160, 120, 220,
	};
	static const uint8_t uvs[16] = {
		128, 128, 85, 255, 44, 21, 255, 107,
		0, 0, 255, 255, 90, 170, 200, 80,
	};
	uint8_t src[12 * 6], dst[8 * 4 * 4 + 16];
	memset(src, 0xa5, sizeof(src));
	memset(dst, 0xa5, sizeof(dst));
	for (unsigned int r = 0; r < 4; r++)
		memcpy(src + r * stride, ys + r * 8, 8);
	for (unsigned int r = 0; r < 2; r++)
		memcpy(src + (4 + r) * stride, uvs + r * 8, 8);
	nv12_to_bgrx(src, src + 4 * stride, stride, dst, 8, 4);
	for (unsigned int r = 0; r < 4; r++) {
		for (unsigned int c = 0; c < 8; c++) {
			int y = ys[r * 8 + c];
			int u = uvs[(r / 2) * 8 + (c & ~1u)] - 128;
			int v = uvs[(r / 2) * 8 + (c & ~1u) + 1] - 128;
			int expected[4] = { reference(y + 1.772 * u),
				reference(y - 0.344136 * u - 0.714136 * v),
				reference(y + 1.402 * v), 0 };
			for (unsigned int ch = 0; ch < 4; ch++) {
				int actual = dst[(r * 8 + c) * 4 + ch];
				if (abs(actual - expected[ch]) > (ch == 3 ? 0 : 2)) {
					fprintf(stderr, "FAIL row=%u col=%u channel=%u: %d != %d\n",
						r, c, ch, actual, expected[ch]);
					exit(1);
				}
			}
		}
	}
	for (unsigned int i = 128; i < sizeof(dst); i++)
		if (dst[i] != 0xa5)
			exit(1);
	printf("PASS 8x4 BT.601 full-range, stride=%u, BGR within +/-2, x=0, guard intact\n", stride);
}

static double now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec * 1e-9;
}

int main(void)
{
	const unsigned int w = 1920, h = 1440, runs = 120;
	size_t pixels = (size_t)w * h;
	uint8_t *src = malloc(pixels * 3 / 2), *dst = malloc(pixels * 4);
	volatile unsigned long checksum = 0;
	double start, elapsed;
	check(8);
	check(12);
	if (!src || !dst)
		return 1;
	for (size_t i = 0; i < pixels * 3 / 2; i++)
		src[i] = (uint8_t)(i * 37 + i / w);
	for (unsigned int i = 0; i < 5; i++)
		nv12_to_bgrx(src, src + pixels, w, dst, w, h);
	/* Check the full-size vectorized path too, outside the timing interval. */
	for (size_t i = 0; i < pixels; i++) {
		size_t uv = pixels + (i / w / 2) * w + (i % w & ~(size_t)1);
		int y = src[i], u = src[uv] - 128, v = src[uv + 1] - 128;
		if (abs(dst[4 * i] - reference(y + 1.772 * u)) > 2 ||
		    abs(dst[4 * i + 1] - reference(y - 0.344136 * u - 0.714136 * v)) > 2 ||
		    abs(dst[4 * i + 2] - reference(y + 1.402 * v)) > 2 ||
		    dst[4 * i + 3] != 0) {
			fprintf(stderr, "FAIL full-size pixel %zu\n", i);
			return 1;
		}
	}
	puts("PASS 1920x1440 BT.601 reference comparison");
	start = now();
	for (unsigned int i = 0; i < runs; i++) {
		src[i] ^= 1;
		nv12_to_bgrx(src, src + pixels, w, dst, w, h);
		checksum += dst[i * 4];
	}
	elapsed = now() - start;
	printf("1920x1440: %u frames, %.3f ms/frame, %.1f fps, %.1f%% of one core at 30 fps; checksum=%lu\n",
		runs, elapsed * 1000 / runs, runs / elapsed,
		elapsed / runs * 30 * 100, checksum);
	free(src);
	free(dst);
	return 0;
}
