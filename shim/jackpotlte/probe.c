/* SPDX-License-Identifier: GPL-2.0-only */
#include "fbtext.h"
#include "fdtmem.h"
#include "probe.h"

#define FDT_MAGIC 0xd00dfeedU
#define FDT_HEADER_BYTES 40U
#define FDT_MAX_BYTES (64U * 1024U * 1024U)

static uint32_t be32(volatile const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) |
           ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) |
           (uint32_t)p[3];
}

static int fdt_header_valid(uintptr_t fdt, uint32_t *total_size)
{
    if (!fdt || (fdt & 7U))
        return 0;

    volatile const uint8_t *header = (volatile const uint8_t *)fdt;
    if (be32(header) != FDT_MAGIC)
        return 0;

    uint32_t size = be32(header + 4);
    if (size < FDT_HEADER_BYTES || size > FDT_MAX_BYTES)
        return 0;

    *total_size = size;
    return 1;
}

void jackpot_probe_main(uintptr_t fdt,
                        const struct jackpot_probe_registers *r,
                        uintptr_t image)
{
    unsigned row = 0;
    jackpot_fb_text(row++, "JACKPOTLTE A530N PROBE");
    jackpot_fb_text(row++, "SBOOT HANDOFF 0003.1");
    jackpot_fb_text(row++, "FDT PARSE START");
    jackpot_fb_hex(row++, "FDT PTR", fdt);
    jackpot_fb_flush();

    uint32_t fdt_size = 0;
    uint32_t fdt_ok = (uint32_t)fdt_header_valid(fdt, &fdt_size);
    uint32_t trigger = jackpot_decon_trigger();
    struct jackpot_fdt_region banks[4];
    struct jackpot_fdt_region reserved[32];
    unsigned bank_count = 0;
    unsigned reserved_count = 0;
    if (fdt_ok)
        jackpot_fdt_parse(fdt, fdt_size, banks, 4U, &bank_count,
                          reserved, 32U, &reserved_count);

    jackpot_fb_text(row++, "FDT PARSE DONE");
    jackpot_fb_hex(row++, "EL", r->current_el >> 2);
    jackpot_fb_hex(row++, "SCTLR", r->sctlr);
    jackpot_fb_hex(row++, "MIDR", r->midr);
    jackpot_fb_hex(row++, "MPIDR", r->mpidr);
    jackpot_fb_hex(row++, "MMFR0", r->mmfr0);
    jackpot_fb_hex(row++, "PFR0", r->pfr0);
    jackpot_fb_hex(row++, "ISAR0", r->isar0);
    jackpot_fb_hex(row++, "CNTFRQ", r->cntfrq);
    jackpot_fb_hex(row++, "CNTPCT", r->cntpct);
    jackpot_fb_hex(row++, "FDT", fdt);
    jackpot_fb_text(row++, fdt_ok ? "FDT HEADER VALID" : "FDT HEADER INVALID");
    if (fdt_ok)
        jackpot_fb_hex(row++, "FDT SIZE", fdt_size);
    if (bank_count) {
        for (unsigned i = 0; i < bank_count && i < 4U; ++i) {
            char label[16] = "RAM0 BASE";
            label[3] = (char)('0' + i);
            jackpot_fb_hex(row++, label, banks[i].base);
            label[5] = 'S';
            label[6] = 'I';
            label[7] = 'Z';
            label[8] = 'E';
            label[9] = '\0';
            jackpot_fb_hex(row++, label, banks[i].size);
        }
    } else if (fdt_ok) {
        jackpot_fb_text(row++, "FDT RAM NOT FOUND");
    }
    if (fdt_ok) {
        jackpot_fb_text(row++, "FDT RESERVED RANGES");
        jackpot_fb_hex(row++, "RSV COUNT", reserved_count);
        if (!reserved_count) {
            jackpot_fb_text(row++, "FDT RESERVED NONE");
        } else {
            unsigned shown = reserved_count < 32U ? reserved_count : 32U;
            for (unsigned i = 0; i < shown; ++i)
                jackpot_fb_region(row++, reserved[i].name,
                                  reserved[i].base, reserved[i].size);
            if (reserved_count > 32U)
                jackpot_fb_text(row++, "RSV LIST TRUNCATED AT 32");
        }
    }
    jackpot_fb_hex(row++, "IMAGE", image);
    uint32_t tgran4 = (uint32_t)((r->mmfr0 >> 28) & 0xfU);
    jackpot_fb_text(row++, tgran4 <= 1U ?
                    "4K GRANULE YES" : "4K GRANULE NO/UNKNOWN");
    jackpot_fb_hex(row++, "FB BASE", JACKPOT_FB_BASE);
    jackpot_fb_hex(row++, "DECON TRIG", trigger);
    jackpot_fb_text(row++, "NO STORAGE WRITES");
    jackpot_fb_text(row++, "FORCED RECOVERY TO EXIT");
    jackpot_fb_flush();

    for (;;)
        __asm__ volatile("wfe");
}
