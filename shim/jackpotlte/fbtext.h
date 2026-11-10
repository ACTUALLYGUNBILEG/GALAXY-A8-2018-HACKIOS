/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once

#include <stdint.h>

/* Values from the Exynos 7885 jackpotlte Korean rev07 kernel DTS. */
#define JACKPOT_FB_BASE       0xEC000000UL
#define JACKPOT_FB_WIDTH      1080U
#define JACKPOT_FB_HEIGHT     2220U
#define JACKPOT_FB_STRIDE     (JACKPOT_FB_WIDTH * 4U)
#define JACKPOT_DECON_F_BASE  0x14860000UL

uint32_t jackpot_decon_trigger(void);
void jackpot_fb_text(unsigned row, const char *text);
void jackpot_fb_hex(unsigned row, const char *label, uint64_t value);
void jackpot_fb_region(unsigned row, const char *label,
                       uint64_t base, uint64_t size);
void jackpot_fb_flush(void);
