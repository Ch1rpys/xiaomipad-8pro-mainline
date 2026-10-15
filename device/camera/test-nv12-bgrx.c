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

static void *allocate(size_t n)
{
	void *p = malloc(n);
	if (!p) {
		perror("malloc");
		exit(1);
	}
	return p;
}

static void compare(const uint8_t *y, const uint8_t *uv, unsigned int stride,
                    unsigned int w, unsigned int h)
{
	size_t bytes = (size_t)w * h * 4;
	/* Offset the destination to exercise unaligned interleaved stores. */
	uint8_t *actual = allocate(bytes + 2), *expected = allocate(bytes + 2);
	memset(actual, 0xa5, bytes + 2);
	memset(expected, 0xa5, bytes + 2);
	nv12_to_bgrx(y, uv, stride, actual + 1, w, h);
	nv12_to_bgrx_ref(y, uv, stride, expected + 1, w, h);
	if (memcmp(actual, expected, bytes + 2)) {
		for (size_t i = 0; i < bytes + 2; i++)
			if (actual[i] != expected[i]) {
				fprintf(stderr, "FAIL %ux%u stride=%u byte=%zu: %u != %u\n",
				        w, h, stride, i, actual[i], expected[i]);
				break;
			}
		exit(1);
	}
	if (actual[0] != 0xa5 || actual[bytes + 1] != 0xa5) {
		fputs("FAIL output guard\n", stderr);
		exit(1);
	}
	free(actual);
	free(expected);
}

static void exhaustive(void)
{
	const unsigned int w = 512, h = 256;
	uint8_t *y = allocate((size_t)w * h), *uv = allocate((size_t)w * h / 2);
	/* A real NV12 frame: Y is row, U is column/2, V is frame number.
	 * Each of the 256^3 triples occurs twice across the SIMD lanes.
	 */
	for (unsigned int r = 0; r < h; r++)
		memset(y + r * w, r, w);
	for (unsigned int v = 0; v < 256; v++) {
		for (unsigned int r = 0; r < h / 2; r++)
			for (unsigned int c = 0; c < w; c += 2) {
				uv[r * w + c] = c / 2;
				uv[r * w + c + 1] = v;
			}
		compare(y, uv, w, w, h);
	}
	free(y);
	free(uv);
	puts("PASS exhaustive 16777216 YUV triples in 256 NV12 512x256 frames (byte-exact)");
}

static uint32_t random_state = 0x735a92d1;

static uint8_t random_byte(void)
{
	random_state ^= random_state << 13;
	random_state ^= random_state >> 17;
	random_state ^= random_state << 5;
	return random_state >> 24;
}

static void random_frames(void)
{
	static const unsigned int widths[] = {2, 14, 16, 18, 30, 34, 1920};
	static const unsigned int pads[] = {0, 2, 17, 64};
	for (size_t wi = 0; wi < sizeof(widths) / sizeof(widths[0]); wi++) {
		unsigned int w = widths[wi], h = w == 1920 ? 1440 : 18;
		for (size_t pi = 0; pi < sizeof(pads) / sizeof(pads[0]); pi++) {
			unsigned int stride = w + pads[pi];
			/* Separate planes, unaligned starts, no trailing allocation slack:
			 * ASan catches accesses beyond the final row on the host path.
			 */
			size_t yn = (size_t)(h - 1) * stride + w;
			size_t uvn = (size_t)(h / 2 - 1) * stride + w;
			uint8_t *y = allocate(yn + 1), *uv = allocate(uvn + 1);
			for (unsigned int trial = 0; trial < 3; trial++) {
				for (size_t i = 0; i <= yn; i++)
					y[i] = random_byte();
				for (size_t i = 0; i <= uvn; i++)
					uv[i] = random_byte();
				compare(y + 1, uv + 1, stride, w, h);
			}
			free(y);
			free(uv);
		}
		printf("PASS random %ux%u: strides width+{0,2,17,64}, 3 frames each, unaligned, byte-exact/guards\n", w, h);
	}
}

/* Volatile dispatch forces every timed frame to be converted, even with LTO;
 * a compiler memory barrier additionally exposes the complete output.
 */
static void (*volatile convert)(const uint8_t *, const uint8_t *, unsigned int,
                               uint8_t *, unsigned int, unsigned int) = nv12_to_bgrx;

static void full_size(int timing)
{
	const unsigned int w = 1920, h = 1440, runs = 100;
	size_t pixels = (size_t)w * h;
	uint8_t *src = allocate(pixels * 3 / 2), *dst = allocate(pixels * 4);
	volatile unsigned long checksum = 0;
	for (size_t i = 0; i < pixels * 3 / 2; i++)
		src[i] = (uint8_t)(i * 37 + i / w);
	nv12_to_bgrx(src, src + pixels, w, dst, w, h);
	/* Retain the independent full-size floating-point BT.601 oracle. */
	for (size_t i = 0; i < pixels; i++) {
		size_t uv = pixels + (i / w / 2) * w + (i % w & ~(size_t)1);
		int y = src[i], u = src[uv] - 128, v = src[uv + 1] - 128;
		if (abs(dst[4 * i] - reference(y + 1.772 * u)) > 2 ||
		    abs(dst[4 * i + 1] - reference(y - 0.344136 * u - 0.714136 * v)) > 2 ||
		    abs(dst[4 * i + 2] - reference(y + 1.402 * v)) > 2 ||
		    dst[4 * i + 3] != 0) {
			fprintf(stderr, "FAIL full-size pixel %zu\n", i);
			exit(1);
		}
	}
	puts("PASS 1920x1440 independent BT.601 reference comparison");
	if (timing) {
		for (unsigned int i = 0; i < 5; i++)
			convert(src, src + pixels, w, dst, w, h);
		double start = now();
		for (unsigned int i = 0; i < runs; i++) {
			src[i] ^= 1;
			convert(src, src + pixels, w, dst, w, h);
			__asm__ volatile("" : : "r"(dst) : "memory");
			checksum += dst[i * 4];
		}
		double elapsed = now() - start;
		printf("1920x1440: %u frames, %.3f ms/frame; checksum=%lu (conversion only)\n",
		       runs, elapsed * 1000 / runs, checksum);
	}
	free(src);
	free(dst);
}

int main(int argc, char **argv)
{
	if (argc == 2 && strcmp(argv[1], "--timing") == 0) {
		full_size(1);
		return 0;
	}
	if (argc != 1) {
		fprintf(stderr, "Usage: %s [--timing]\nDefault: exhaustive, random/tails and independent correctness checks.\n"
		        "--timing: 5 warmups, 100 frames 1920x1440; run natively for timing.\n", argv[0]);
		return 2;
	}
#ifdef __aarch64__
	puts("Path: AArch64 NEON + scalar tails");
#else
	puts("Path: non-AArch64 scalar fallback");
#endif
	check(8);
	check(12);
	exhaustive();
	random_frames();
	full_size(0);
	return 0;
}
