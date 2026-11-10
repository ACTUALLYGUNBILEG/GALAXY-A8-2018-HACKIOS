/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once

#include <stdint.h>

struct jackpot_fdt_region {
    uint64_t base;
    uint64_t size;
    char name[16];
};

void jackpot_fdt_parse(uintptr_t fdt, uint32_t available_bytes,
                       struct jackpot_fdt_region *banks,
                       unsigned bank_capacity, unsigned *bank_count,
                       struct jackpot_fdt_region *reserved,
                       unsigned reserved_capacity, unsigned *reserved_count);

int jackpot_fdt_chosen_u64(uintptr_t fdt, uint32_t available_bytes,
                           const char *property, uint64_t *value);
