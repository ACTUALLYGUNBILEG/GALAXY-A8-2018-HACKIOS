/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Small status console for the jackpotlte S-Boot framebuffer.
 *
 * The 5x7 glyph table is adapted from wardevsa/ios-a5xelte's GPL-2.0-only
 * shim/herolte/fbtext.c. Framebuffer and DECON addresses come from the
 * Exynos 7885 Korean jackpotlte device tree and decon register definitions.
 */
#include "fbtext.h"

#include <stddef.h>

struct glyph {
    char ch;
    uint8_t rows[7];
};

static const struct glyph font[] = {
    {' ', {0, 0, 0, 0, 0, 0, 0}},
    {':', {0, 4, 4, 0, 4, 4, 0}},
    {'?', {14, 17, 1, 2, 4, 0, 4}},
    {'.', {0, 0, 0, 0, 0, 12, 12}},
    {'-', {0, 0, 0, 31, 0, 0, 0}},
    {'+', {0, 4, 4, 31, 4, 4, 0}},
    {'0', {14, 17, 19, 21, 25, 17, 14}},
    {'1', {4, 12, 4, 4, 4, 4, 14}},
    {'2', {14, 17, 1, 2, 4, 8, 31}},
    {'3', {30, 1, 1, 14, 1, 1, 30}},
    {'4', {2, 6, 10, 18, 31, 2, 2}},
    {'5', {31, 16, 30, 1, 1, 17, 14}},
    {'6', {6, 8, 16, 30, 17, 17, 14}},
    {'7', {31, 1, 2, 4, 8, 8, 8}},
    {'8', {14, 17, 17, 14, 17, 17, 14}},
    {'9', {14, 17, 17, 15, 1, 2, 12}},
    {'A', {14, 17, 17, 31, 17, 17, 17}},
    {'B', {30, 17, 17, 30, 17, 17, 30}},
    {'C', {14, 17, 16, 16, 16, 17, 14}},
    {'D', {30, 17, 17, 17, 17, 17, 30}},
    {'E', {31, 16, 16, 30, 16, 16, 31}},
    {'F', {31, 16, 16, 30, 16, 16, 16}},
    {'G', {14, 17, 16, 23, 17, 17, 14}},
    {'H', {17, 17, 17, 31, 17, 17, 17}},
    {'I', {14, 4, 4, 4, 4, 4, 14}},
    {'J', {7, 2, 2, 2, 18, 18, 12}},
    {'K', {17, 18, 20, 24, 20, 18, 17}},
    {'L', {16, 16, 16, 16, 16, 16, 31}},
    {'M', {17, 27, 21, 21, 17, 17, 17}},
    {'N', {17, 25, 21, 19, 17, 17, 17}},
    {'O', {14, 17, 17, 17, 17, 17, 14}},
    {'P', {30, 17, 17, 30, 16, 16, 16}},
    {'Q', {14, 17, 17, 17, 21, 18, 13}},
    {'R', {30, 17, 17, 30, 20, 18, 17}},
    {'S', {15, 16, 16, 14, 1, 1, 30}},
    {'T', {31, 4, 4, 4, 4, 4, 4}},
    {'U', {17, 17, 17, 17, 17, 17, 14}},
    {'V', {17, 17, 17, 17, 17, 10, 4}},
    {'W', {17, 17, 17, 21, 21, 21, 10}},
    {'X', {17, 17, 10, 4, 10, 17, 17}},
    {'Y', {17, 17, 10, 4, 4, 4, 4}},
    {'Z', {31, 1, 2, 4, 8, 16, 31}},
};

#define SCALE       3U
#define CELL_WIDTH  (6U * SCALE)
#define CELL_HEIGHT (9U * SCALE)
#define LEFT        24U
#define TOP         72U
#define ROW_WIDTH   (JACKPOT_FB_WIDTH - 2U * LEFT)

static const uint8_t *glyph_for(char ch)
{
    if (ch >= 'a' && ch <= 'z')
        ch = (char)(ch - ('a' - 'A'));
    for (unsigned i = 0; i < sizeof(font) / sizeof(font[0]); ++i) {
        if (font[i].ch == ch)
            return font[i].rows;
    }
    return font[2].rows;
}

static void fill_row(unsigned row, uint32_t pixel)
{
    volatile uint32_t *fb = (volatile uint32_t *)JACKPOT_FB_BASE;
    unsigned y0 = TOP + row * CELL_HEIGHT;
    unsigned x0 = LEFT;

    if (y0 + CELL_HEIGHT > JACKPOT_FB_HEIGHT)
        return;
    for (unsigned y = y0; y < y0 + CELL_HEIGHT; ++y) {
        volatile uint32_t *dst = fb + (size_t)y * JACKPOT_FB_WIDTH + x0;
        for (unsigned x = 0; x < ROW_WIDTH; ++x)
            dst[x] = pixel;
    }
}

void jackpot_fb_text(unsigned row, const char *text)
{
    volatile uint32_t *fb = (volatile uint32_t *)JACKPOT_FB_BASE;
    unsigned y0 = TOP + row * CELL_HEIGHT + SCALE;

    if (y0 + 7U * SCALE >= JACKPOT_FB_HEIGHT)
        return;
    fill_row(row, 0xff000000U);

    for (unsigned col = 0;
         text[col] && LEFT + (col + 1U) * CELL_WIDTH <= JACKPOT_FB_WIDTH - LEFT;
         ++col) {
        const uint8_t *glyph = glyph_for(text[col]);
        for (unsigned y = 0; y < 7; ++y) {
            for (unsigned x = 0; x < 5; ++x) {
                if (!(glyph[y] & (1U << (4U - x))))
                    continue;
                for (unsigned sy = 0; sy < SCALE; ++sy) {
                    for (unsigned sx = 0; sx < SCALE; ++sx) {
                        unsigned px = LEFT + col * CELL_WIDTH + x * SCALE + sx;
                        unsigned py = y0 + y * SCALE + sy;
                        fb[(size_t)py * JACKPOT_FB_WIDTH + px] = 0xffffffffU;
                    }
                }
            }
        }
    }
}

void jackpot_fb_hex(unsigned row, const char *label, uint64_t value)
{
    static const char hex[] = "0123456789ABCDEF";
    char line[40];
    unsigned n = 0;

    while (label[n] && n < 18U) {
        line[n] = label[n];
        ++n;
    }
    line[n++] = ':';
    line[n++] = ' ';
    for (int shift = 60; shift >= 0; shift -= 4)
        line[n++] = hex[(value >> shift) & 0xfU];
    line[n] = '\0';
    jackpot_fb_text(row, line);
}

void jackpot_fb_region(unsigned row, const char *label,
                       uint64_t base, uint64_t size)
{
    static const char hex[] = "0123456789ABCDEF";
    char line[64];
    unsigned n = 0;

    while (label[n] && n < 14U) {
        line[n] = label[n];
        ++n;
    }
    line[n++] = ':';
    line[n++] = ' ';
    for (int shift = 60; shift >= 0; shift -= 4)
        line[n++] = hex[(base >> shift) & 0xfU];
    line[n++] = '+';
    for (int shift = 60; shift >= 0; shift -= 4)
        line[n++] = hex[(size >> shift) & 0xfU];
    line[n] = '\0';
    jackpot_fb_text(row, line);
}

uint32_t jackpot_decon_trigger(void)
{
    volatile uint32_t *trigger =
        (volatile uint32_t *)(JACKPOT_DECON_F_BASE + 0x70U);
    return *trigger;
}

void jackpot_fb_flush(void)
{
    /* Exynos 7885 DECON_F: HW_TRIG_EN bit 0, MASK_DECON bit 4. */
    volatile uint32_t *trigger =
        (volatile uint32_t *)(JACKPOT_DECON_F_BASE + 0x70U);
    uint32_t value = *trigger;
    value &= ~((1U << 0) | (1U << 4));
    value |= 1U << 0;
    *trigger = value;

    __asm__ volatile("dsb sy" : : : "memory");

    /* Update the active four DECON windows plus the global shadow registers. */
    volatile uint32_t *update =
        (volatile uint32_t *)(JACKPOT_DECON_F_BASE + 0x60U);
    *update |= (1U << 31) | 0x0fU;
    __asm__ volatile("dsb sy" : : : "memory");
}
