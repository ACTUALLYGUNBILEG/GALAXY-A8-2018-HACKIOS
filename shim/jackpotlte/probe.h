/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once

#include <stdint.h>

struct jackpot_probe_registers {
    uint64_t current_el;
    uint64_t sctlr;
    uint64_t midr;
    uint64_t mpidr;
    uint64_t mmfr0;
    uint64_t pfr0;
    uint64_t isar0;
    uint64_t cntfrq;
    uint64_t cntpct;
};

void jackpot_probe_main(uintptr_t fdt,
                        const struct jackpot_probe_registers *registers,
                        uintptr_t image);
