/* SPDX-License-Identifier: GPL-2.0-only */
/* First XNU handoff for Galaxy A8 2018 SM-A530N / Exynos 7885. */
#include "fbtext.h"
#include "fdtmem.h"

#include <stddef.h>
#include <stdint.h>

#define XNU_RAM_BASE 0x880000000ULL
#define XNU_RAM_SIZE 0x20000000ULL
#define XNU_RAM_END (XNU_RAM_BASE + XNU_RAM_SIZE)
#define PAGE_SIZE 0x1000ULL
#define BOOT_LINE_LENGTH 608U
#define FDT_MAGIC 0xd00dfeedU
#define FDT_HEADER_BYTES 40U
#define FDT_MAX_BYTES (64U * 1024U * 1024U)
#define MAX_BANKS 8U
#define MAX_RESERVED 32U
#define MAX_SEGMENTS 32U

struct xnu_payload_segment {
    uint64_t vmaddr;
    uint64_t vmsize;
    uint64_t file_offset;
    uint64_t file_size;
};

struct xnu_payload {
    char magic[8];
    uint32_t version;
    uint32_t segment_count;
    uint64_t virtual_base;
    uint64_t entry_va;
    uint64_t adt_offset;
    uint64_t adt_size;
    uint64_t kernel_end_va;
    uint64_t physical_base;
    uint64_t memory_size;
    char command_line[BOOT_LINE_LENGTH];
    struct xnu_payload_segment segments[];
};

struct boot_video {
    uint64_t base_address;
    uint64_t display;
    uint64_t row_bytes;
    uint64_t width;
    uint64_t height;
    uint64_t depth;
};

struct boot_args {
    uint16_t revision;
    uint16_t version;
    uint64_t virtual_base;
    uint64_t physical_base;
    uint64_t memory_size;
    uint64_t top_of_kernel_data;
    struct boot_video video;
    uint32_t machine_type;
    uint64_t device_tree;
    uint32_t device_tree_length;
    char command_line[BOOT_LINE_LENGTH];
    uint64_t boot_flags;
    uint64_t memory_size_actual;
};

struct handoff {
    uint64_t entry_pa;
    uint64_t boot_args_pa;
};

_Static_assert(offsetof(struct xnu_payload, segments) == 0x2a8,
               "payload header layout mismatch");
_Static_assert(sizeof(struct xnu_payload_segment) == 32,
               "payload segment layout mismatch");
_Static_assert(offsetof(struct boot_args, command_line) == 108,
               "boot_args command-line offset mismatch");
_Static_assert(sizeof(struct boot_args) == 736,
               "boot_args size mismatch");

static uint32_t read_be32(const volatile uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static int fdt_size(uintptr_t fdt, uint32_t *size)
{
    if (!fdt || (fdt & 7U))
        return 0;
    const volatile uint8_t *header = (const volatile uint8_t *)fdt;
    if (read_be32(header) != FDT_MAGIC)
        return 0;
    uint32_t total = read_be32(header + 4U);
    if (total < FDT_HEADER_BYTES || total > FDT_MAX_BYTES)
        return 0;
    *size = total;
    return 1;
}

static void zero_bytes(uintptr_t destination, uint64_t size)
{
    volatile uint8_t *d8 = (volatile uint8_t *)destination;
    while (size && (destination & 7U)) {
        *d8++ = 0;
        ++destination;
        --size;
    }
    volatile uint64_t *d64 = (volatile uint64_t *)destination;
    while (size >= sizeof(*d64)) {
        *d64++ = 0;
        size -= sizeof(*d64);
    }
    d8 = (volatile uint8_t *)d64;
    for (uint64_t i = 0; i < size; ++i)
        d8[i] = 0;
}

static void copy_bytes(uintptr_t destination, uintptr_t source, uint64_t size)
{
    volatile uint8_t *d = (volatile uint8_t *)destination;
    volatile const uint8_t *s = (volatile const uint8_t *)source;
    for (uint64_t i = 0; i < size; ++i)
        d[i] = s[i];
}

static void clean_bytes(uintptr_t start, uintptr_t end)
{
    uint64_t ctr;
    __asm__ volatile("mrs %0, CTR_EL0" : "=r"(ctr));
    uintptr_t line_size = 4UL << ((ctr >> 16) & 0xfU);
    for (uintptr_t p = start & ~(line_size - 1U); p < end; p += line_size)
        __asm__ volatile("dc cvac, %0" : : "r"(p) : "memory");
    __asm__ volatile("dsb sy" : : : "memory");
}

static uintptr_t align_page(uintptr_t value)
{
    return (value + PAGE_SIZE - 1U) & ~(PAGE_SIZE - 1U);
}

static int magic_ok(const char *value)
{
    static const char expected[8] = {'S', 'W', 'E', 'E', 'T', 'X', 'N', 'U'};
    for (unsigned i = 0; i < sizeof(expected); ++i) {
        if (value[i] != expected[i])
            return 0;
    }
    return 1;
}

static int range_in_ram(uint64_t start, uint64_t end,
                        const struct jackpot_fdt_region *banks,
                        unsigned bank_count)
{
    if (end <= start)
        return 0;
    for (unsigned i = 0; i < bank_count && i < MAX_BANKS; ++i) {
        uint64_t bank_end = banks[i].base + banks[i].size;
        if (bank_end >= banks[i].base && start >= banks[i].base && end <= bank_end)
            return 1;
    }
    return 0;
}

static void loader_error(const char *message, uint64_t value)
{
    jackpot_fb_text(0, "JACKPOTLTE XNU LOADER");
    jackpot_fb_text(1, message);
    jackpot_fb_hex(2, "VALUE", value);
    jackpot_fb_text(3, "NO STORAGE WRITES");
    jackpot_fb_text(4, "USE KEYS FOR TWRP");
    jackpot_fb_flush();
}

/* Catches faults before XNU installs its own early exception vectors. */
void jackpot_xnu_exception(uint64_t vector, uint64_t esr,
                           uint64_t elr, uint64_t far)
{
    jackpot_fb_text(0, "LOADER EXCEPTION BEFORE XNU");
    jackpot_fb_hex(1, "VECTOR", vector);
    jackpot_fb_hex(2, "ESR", esr);
    jackpot_fb_hex(3, "ELR", elr);
    jackpot_fb_hex(4, "FAR", far);
    jackpot_fb_text(5, "USE TWRP BACKUP IF NEEDED");
    jackpot_fb_flush();
    for (;;)
        __asm__ volatile("wfe");
}

struct handoff jackpot_xnu_prepare(uintptr_t fdt)
{
    struct handoff result = {0, 0};
    jackpot_fb_text(0, "XNU LOADER ENTERED");
    jackpot_fb_hex(1, "FDT POINTER", fdt);
    jackpot_fb_flush();

    uint32_t tree_size = 0;
    if (!fdt_size(fdt, &tree_size)) {
        loader_error("FDT HEADER INVALID", fdt);
        return result;
    }
    jackpot_fb_hex(2, "FDT BYTES", tree_size);
    jackpot_fb_flush();

    uint64_t initrd_start = 0;
    uint64_t initrd_end = 0;
    if (!jackpot_fdt_chosen_u64(fdt, tree_size, "linux,initrd-start", &initrd_start) ||
        !jackpot_fdt_chosen_u64(fdt, tree_size, "linux,initrd-end", &initrd_end) ||
        initrd_end <= initrd_start) {
        loader_error("INITRD FDT RANGE MISSING", fdt);
        return result;
    }

    struct jackpot_fdt_region banks[MAX_BANKS];
    struct jackpot_fdt_region reserved[MAX_RESERVED];
    zero_bytes((uintptr_t)banks, sizeof(banks));
    zero_bytes((uintptr_t)reserved, sizeof(reserved));
    unsigned bank_count = 0;
    unsigned reserved_count = 0;
    jackpot_fdt_parse(fdt, tree_size, banks, MAX_BANKS, &bank_count,
                      reserved, MAX_RESERVED, &reserved_count);
    (void)reserved;
    (void)reserved_count;
    if (!bank_count || bank_count > MAX_BANKS ||
        !range_in_ram(initrd_start, initrd_end, banks, bank_count)) {
        loader_error("INITRD OUTSIDE LIVE RAM", initrd_start);
        return result;
    }
    if (initrd_start < XNU_RAM_END && XNU_RAM_BASE < initrd_end) {
        loader_error("INITRD OVERLAPS XNU RAM", initrd_start);
        return result;
    }

    uint64_t payload_length = initrd_end - initrd_start;
    if (payload_length < offsetof(struct xnu_payload, segments)) {
        loader_error("INITRD TOO SMALL", payload_length);
        return result;
    }
    const struct xnu_payload *payload =
        (const struct xnu_payload *)(uintptr_t)initrd_start;
    uint64_t table_end = offsetof(struct xnu_payload, segments) +
                         (uint64_t)payload->segment_count * sizeof(payload->segments[0]);
    if (!magic_ok(payload->magic) || payload->version != 1U ||
        !payload->segment_count || payload->segment_count > MAX_SEGMENTS ||
        table_end > payload_length || payload->adt_offset < table_end ||
        payload->adt_offset > payload_length ||
        payload->adt_size > payload_length - payload->adt_offset ||
        !payload->adt_size || payload->adt_size > 1024U * 1024U) {
        loader_error("PAYLOAD HEADER INVALID", payload_length);
        return result;
    }
    if (payload->physical_base != XNU_RAM_BASE ||
        payload->memory_size != XNU_RAM_SIZE ||
        payload->physical_base + payload->memory_size != XNU_RAM_END ||
        payload->virtual_base >= payload->entry_va ||
        payload->entry_va >= payload->kernel_end_va ||
        payload->kernel_end_va <= payload->virtual_base ||
        payload->kernel_end_va - payload->virtual_base > payload->memory_size) {
        loader_error("XNU RAM OR ENTRY INVALID", payload->physical_base);
        return result;
    }

    uint64_t max_segment_end = payload->virtual_base;
    for (uint32_t i = 0; i < payload->segment_count; ++i) {
        const struct xnu_payload_segment *segment = &payload->segments[i];
        if (segment->vmaddr < payload->virtual_base ||
            segment->file_size > segment->vmsize ||
            segment->file_offset < table_end ||
            segment->file_offset > payload->adt_offset ||
            segment->file_size > payload->adt_offset - segment->file_offset ||
            segment->vmsize > payload->memory_size ||
            segment->vmaddr - payload->virtual_base >
                payload->memory_size - segment->vmsize ||
            segment->vmaddr % PAGE_SIZE) {
            loader_error("XNU SEGMENT INVALID", i);
            return result;
        }
        uint64_t segment_end = segment->vmaddr + segment->vmsize;
        if (segment_end < segment->vmaddr) {
            loader_error("XNU SEGMENT OVERFLOW", i);
            return result;
        }
        if (segment_end > max_segment_end)
            max_segment_end = segment_end;
        for (uint32_t j = 0; j < i; ++j) {
            const struct xnu_payload_segment *prior = &payload->segments[j];
            if (segment->vmaddr < prior->vmaddr + prior->vmsize &&
                prior->vmaddr < segment_end) {
                loader_error("XNU SEGMENTS OVERLAP", i);
                return result;
            }
        }
    }
    if (align_page((uintptr_t)max_segment_end) != payload->kernel_end_va) {
        loader_error("KERNEL END MISMATCH", max_segment_end);
        return result;
    }

    uint64_t adt_pa = payload->physical_base +
                      (payload->kernel_end_va - payload->virtual_base);
    if (adt_pa < payload->physical_base || adt_pa >= XNU_RAM_END ||
        payload->adt_size > XNU_RAM_END - adt_pa) {
        loader_error("ADT DESTINATION INVALID", adt_pa);
        return result;
    }
    uint64_t boot_args_pa = align_page((uintptr_t)(adt_pa + payload->adt_size));
    if (boot_args_pa + PAGE_SIZE > XNU_RAM_END || boot_args_pa < adt_pa) {
        loader_error("BOOT ARGS OUTSIDE RAM", boot_args_pa);
        return result;
    }

    jackpot_fb_text(0, "JACKPOTLTE XNU LOADER");
    jackpot_fb_hex(1, "INITRD START", initrd_start);
    jackpot_fb_hex(2, "INITRD END", initrd_end);
    jackpot_fb_hex(3, "XNU PHYS BASE", payload->physical_base);
    jackpot_fb_hex(4, "XNU KERNEL END", max_segment_end);
    jackpot_fb_text(5, "ZEROING XNU RAM2");
    jackpot_fb_flush();

    /* Match the donor handoff: S-Boot leaves stale bytes where iBoot provides
     * zeroed RAM, and XNU's early VM bootstrap can stall on those contents. */
    zero_bytes((uintptr_t)payload->physical_base, payload->memory_size);
    jackpot_fb_text(5, "XNU RAM2 ZEROED");
    jackpot_fb_flush();
    jackpot_fb_text(6, "COPYING XNU SEGMENTS");
    jackpot_fb_flush();

    for (uint32_t i = 0; i < payload->segment_count; ++i) {
        const struct xnu_payload_segment *segment = &payload->segments[i];
        uintptr_t destination = payload->physical_base +
                                (segment->vmaddr - payload->virtual_base);
        copy_bytes(destination, initrd_start + segment->file_offset,
                   segment->file_size);
        zero_bytes(destination + segment->file_size,
                   segment->vmsize - segment->file_size);
        clean_bytes(destination, destination + segment->vmsize);
    }

    copy_bytes(adt_pa, initrd_start + payload->adt_offset, payload->adt_size);
    zero_bytes(boot_args_pa, PAGE_SIZE);
    struct boot_args *args = (struct boot_args *)(uintptr_t)boot_args_pa;
    args->revision = 2;
    args->version = 2;
    args->virtual_base = payload->virtual_base;
    args->physical_base = payload->physical_base;
    args->memory_size = payload->memory_size;
    args->top_of_kernel_data = boot_args_pa + PAGE_SIZE;
    args->video.base_address = 0xEC000000ULL;
    args->video.display = 1;
    args->video.row_bytes = 4320;
    args->video.width = 1080;
    args->video.height = 2220;
    args->video.depth = 32;
    args->machine_type = 0;
    args->device_tree = payload->virtual_base + (adt_pa - payload->physical_base);
    args->device_tree_length = (uint32_t)payload->adt_size;
    for (unsigned i = 0; i < BOOT_LINE_LENGTH; ++i)
        args->command_line[i] = payload->command_line[i];
    args->memory_size_actual = payload->memory_size;
    clean_bytes(adt_pa, boot_args_pa + PAGE_SIZE);
    jackpot_fb_text(6, "XNU SEGMENTS COPIED");
    jackpot_fb_flush();

    uint64_t entry_pa = payload->physical_base +
                        (payload->entry_va - payload->virtual_base);
    if (entry_pa < payload->physical_base || entry_pa >= adt_pa) {
        loader_error("ENTRY PHYSICAL ADDRESS BAD", entry_pa);
        return result;
    }
    result.entry_pa = entry_pa;
    result.boot_args_pa = boot_args_pa;
    jackpot_fb_hex(6, "XNU ENTRY PA", entry_pa);
    jackpot_fb_hex(7, "BOOT ARGS PA", boot_args_pa);
    jackpot_fb_text(8, "HANDOFF TO XNU");
    jackpot_fb_flush();
    clean_bytes(JACKPOT_FB_BASE, JACKPOT_FB_BASE + 0x1000U);
    return result;
}
