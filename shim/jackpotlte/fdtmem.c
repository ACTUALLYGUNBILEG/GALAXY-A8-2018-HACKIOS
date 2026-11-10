/* SPDX-License-Identifier: GPL-2.0-only */
/* Minimal bounded FDT reader for the S-Boot memory handoff probe. */
#include "fdtmem.h"

#define FDT_MAGIC       0xd00dfeedU
#define FDT_HEADER_SIZE 40U
#define FDT_BEGIN_NODE  1U
#define FDT_END_NODE    2U
#define FDT_PROP        3U
#define FDT_NOP         4U
#define FDT_END         9U
#define FDT_MAX_DEPTH   32U

struct node_context {
    uint32_t address_cells;
    uint32_t size_cells;
    uint32_t is_memory;
    uint32_t is_reserved_parent;
    uint32_t is_reserved_child;
    const uint8_t *name;
    uint32_t name_length;
};

static void copy_node_context(struct node_context *destination,
                              const struct node_context *source)
{
    destination->address_cells = source->address_cells;
    destination->size_cells = source->size_cells;
    destination->is_memory = source->is_memory;
    destination->is_reserved_parent = source->is_reserved_parent;
    destination->is_reserved_child = source->is_reserved_child;
    destination->name = source->name;
    destination->name_length = source->name_length;
}

static uint32_t read_be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) |
           ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) |
           (uint32_t)p[3];
}

static uint64_t read_be64(const uint8_t *p)
{
    return ((uint64_t)read_be32(p) << 32) | read_be32(p + 4U);
}

static int string_is(const uint8_t *data, uint32_t length, const char *text)
{
    uint32_t i = 0;

    while (text[i]) {
        if (i >= length || data[i] != (uint8_t)text[i])
            return 0;
        ++i;
    }
    return i < length && data[i] == 0;
}

static int fdt_string_is(const uint8_t *strings, uint32_t strings_size,
                         uint32_t offset, const char *text)
{
    if (offset >= strings_size)
        return 0;
    return string_is(strings + offset, strings_size - offset, text);
}

static int node_name_is(const uint8_t *name, uint32_t length,
                        const char *text)
{
    return string_is(name, length + 1U, text);
}

static int node_is_memory(const uint8_t *name, uint32_t length)
{
    static const char prefix[] = "memory";

    if (length < sizeof(prefix) - 1U)
        return 0;
    for (uint32_t i = 0; i < sizeof(prefix) - 1U; ++i) {
        if (name[i] != (uint8_t)prefix[i])
            return 0;
    }
    return length == sizeof(prefix) - 1U || name[sizeof(prefix) - 1U] == '@';
}

static uint64_t read_cells(const uint8_t *p, uint32_t cells)
{
    uint64_t value = 0;
    for (uint32_t i = 0; i < cells; ++i)
        value = (value << 32) | read_be32(p + i * 4U);
    return value;
}

static void copy_region_name(char *destination, uint32_t capacity,
                             const uint8_t *name, uint32_t name_length)
{
    uint32_t copied = 0;

    while (copied + 1U < capacity && copied < name_length && name[copied]) {
        if (name[copied] == '@')
            break;
        destination[copied] = name[copied] == '_' ? '-' : (char)name[copied];
        ++copied;
    }
    destination[copied] = '\0';
}

static unsigned parse_reg(const uint8_t *value, uint32_t length,
                          uint32_t address_cells, uint32_t size_cells,
                          struct jackpot_fdt_region *regions,
                          unsigned count, unsigned capacity,
                          const uint8_t *name, uint32_t name_length)
{
    uint32_t tuple_cells = address_cells + size_cells;
    if (!address_cells || address_cells > 2U ||
        !size_cells || size_cells > 2U || tuple_cells > 4U ||
        length % (tuple_cells * 4U))
        return count;

    uint32_t tuples = length / (tuple_cells * 4U);
    for (uint32_t i = 0; i < tuples; ++i) {
        const uint8_t *tuple = value + i * tuple_cells * 4U;
        uint64_t base = read_cells(tuple, address_cells);
        uint64_t size = read_cells(tuple + address_cells * 4U, size_cells);
        if (!size || base + size < base)
            continue;
        if (count < capacity) {
            regions[count].base = base;
            regions[count].size = size;
            copy_region_name(regions[count].name,
                             sizeof(regions[count].name), name, name_length);
        }
        ++count;
    }
    return count;
}

static void parse_fdt(uintptr_t fdt_address, uint32_t available_bytes,
                      struct jackpot_fdt_region *banks,
                      unsigned bank_capacity, unsigned *bank_count,
                      struct jackpot_fdt_region *reserved,
                      unsigned reserved_capacity, unsigned *reserved_count)
{
    if (bank_count)
        *bank_count = 0;
    if (reserved_count)
        *reserved_count = 0;
    if (!fdt_address || (fdt_address & 7U))
        return;

    const uint8_t *fdt = (const uint8_t *)fdt_address;
    if (read_be32(fdt) != FDT_MAGIC)
        return;
    uint32_t total_size = read_be32(fdt + 4U);
    if (total_size < FDT_HEADER_SIZE || total_size > available_bytes)
        return;

    uint32_t struct_offset = read_be32(fdt + 8U);
    uint32_t strings_offset = read_be32(fdt + 12U);
    uint32_t struct_size = read_be32(fdt + 36U);
    uint32_t strings_size = read_be32(fdt + 32U);
    if (struct_offset > total_size || struct_size > total_size - struct_offset ||
        strings_offset > total_size || strings_size > total_size - strings_offset)
        return;

    const uint8_t *structure = fdt + struct_offset;
    const uint8_t *strings = fdt + strings_offset;
    struct node_context stack[FDT_MAX_DEPTH];
    int depth = -1;
    uint32_t offset = 0;
    unsigned banks_found = 0;
    unsigned reserved_found = 0;

    uint32_t reserve_map_offset = read_be32(fdt + 16U);
    if (reserve_map_offset <= total_size) {
        uint32_t reserve_offset = reserve_map_offset;
        while (reserve_offset <= total_size &&
               total_size - reserve_offset >= 16U) {
            uint64_t base = read_be64(fdt + reserve_offset);
            uint64_t size = read_be64(fdt + reserve_offset + 8U);
            reserve_offset += 16U;
            if (!base && !size)
                break;
            if (!size || base + size < base)
                continue;
            if (reserved_found < reserved_capacity) {
                reserved[reserved_found].base = base;
                reserved[reserved_found].size = size;
                copy_region_name(reserved[reserved_found].name,
                                 sizeof(reserved[reserved_found].name),
                                 (const uint8_t *)"fdt-reserve-map", 15U);
            }
            ++reserved_found;
        }
    }

    while (offset + 4U <= struct_size) {
        uint32_t token = read_be32(structure + offset);
        offset += 4U;

        if (token == FDT_BEGIN_NODE) {
            if ((unsigned)(depth + 1) >= FDT_MAX_DEPTH)
                break;
            ++depth;
            if (depth == 0) {
                stack[depth].address_cells = 2U;
                stack[depth].size_cells = 1U;
                stack[depth].is_memory = 0U;
                stack[depth].is_reserved_parent = 0U;
                stack[depth].is_reserved_child = 0U;
            } else {
                copy_node_context(&stack[depth], &stack[depth - 1]);
                stack[depth].is_memory = 0U;
                stack[depth].is_reserved_parent = 0U;
                stack[depth].is_reserved_child = 0U;
            }

            uint32_t name_start = offset;
            while (offset < struct_size && structure[offset])
                ++offset;
            if (offset == struct_size)
                break;
            uint32_t name_length = offset - name_start;
            stack[depth].name = structure + name_start;
            stack[depth].name_length = name_length;
            if (node_is_memory(structure + name_start, name_length))
                stack[depth].is_memory = 1U;
            if (depth == 1 &&
                node_name_is(structure + name_start, name_length,
                             "reserved-memory"))
                stack[depth].is_reserved_parent = 1U;
            if (depth == 2 && stack[depth - 1].is_reserved_parent)
                stack[depth].is_reserved_child = 1U;
            ++offset;
            offset = (offset + 3U) & ~3U;
        } else if (token == FDT_END_NODE) {
            if (depth < 0)
                break;
            --depth;
        } else if (token == FDT_PROP) {
            if (depth < 0 || offset + 8U > struct_size)
                break;
            uint32_t length = read_be32(structure + offset);
            uint32_t name_offset = read_be32(structure + offset + 4U);
            offset += 8U;
            if (length > struct_size - offset || name_offset >= strings_size)
                break;

            const uint8_t *value = structure + offset;
            if (fdt_string_is(strings, strings_size, name_offset,
                              "#address-cells") && length == 4U) {
                stack[depth].address_cells = read_be32(value);
            } else if (fdt_string_is(strings, strings_size, name_offset,
                                     "#size-cells") && length == 4U) {
                stack[depth].size_cells = read_be32(value);
            } else if (stack[depth].is_memory &&
                       fdt_string_is(strings, strings_size, name_offset, "reg")) {
                banks_found = parse_reg(value, length,
                                        stack[depth].address_cells,
                                        stack[depth].size_cells,
                                        banks, banks_found, bank_capacity,
                                        stack[depth].name,
                                        stack[depth].name_length);
            } else if (stack[depth].is_reserved_child &&
                       fdt_string_is(strings, strings_size, name_offset, "reg")) {
                reserved_found = parse_reg(value, length,
                                           stack[depth].address_cells,
                                           stack[depth].size_cells,
                                           reserved, reserved_found,
                                           reserved_capacity,
                                           stack[depth].name,
                                           stack[depth].name_length);
            } else if (fdt_string_is(strings, strings_size, name_offset,
                                     "device_type") &&
                       string_is(value, length, "memory")) {
                stack[depth].is_memory = 1U;
            }

            offset += length;
            offset = (offset + 3U) & ~3U;
        } else if (token == FDT_NOP) {
            continue;
        } else if (token == FDT_END) {
            break;
        } else {
            break;
        }
    }

    if (bank_count)
        *bank_count = banks_found;
    if (reserved_count)
        *reserved_count = reserved_found;
}

void jackpot_fdt_parse(uintptr_t fdt, uint32_t available_bytes,
                       struct jackpot_fdt_region *banks,
                       unsigned bank_capacity, unsigned *bank_count,
                       struct jackpot_fdt_region *reserved,
                       unsigned reserved_capacity, unsigned *reserved_count)
{
    parse_fdt(fdt, available_bytes, banks, bank_capacity, bank_count,
              reserved, reserved_capacity, reserved_count);
}

int jackpot_fdt_chosen_u64(uintptr_t fdt_address, uint32_t available_bytes,
                           const char *property, uint64_t *value)
{
    if (!fdt_address || (fdt_address & 7U) || !property || !value)
        return 0;

    const uint8_t *fdt = (const uint8_t *)fdt_address;
    if (read_be32(fdt) != FDT_MAGIC)
        return 0;
    uint32_t total_size = read_be32(fdt + 4U);
    if (total_size < FDT_HEADER_SIZE || total_size > available_bytes)
        return 0;

    uint32_t struct_offset = read_be32(fdt + 8U);
    uint32_t strings_offset = read_be32(fdt + 12U);
    uint32_t strings_size = read_be32(fdt + 32U);
    uint32_t struct_size = read_be32(fdt + 36U);
    if (struct_offset > total_size || struct_size > total_size - struct_offset ||
        strings_offset > total_size || strings_size > total_size - strings_offset)
        return 0;

    const uint8_t *structure = fdt + struct_offset;
    const uint8_t *strings = fdt + strings_offset;
    uint8_t chosen[FDT_MAX_DEPTH] = {0};
    int depth = -1;
    uint32_t offset = 0;

    while (offset + 4U <= struct_size) {
        uint32_t token = read_be32(structure + offset);
        offset += 4U;

        if (token == FDT_BEGIN_NODE) {
            if ((unsigned)(depth + 1) >= FDT_MAX_DEPTH)
                return 0;
            ++depth;
            uint32_t name_start = offset;
            while (offset < struct_size && structure[offset])
                ++offset;
            if (offset == struct_size)
                return 0;
            uint32_t name_length = offset - name_start;
            chosen[depth] = (uint8_t)(depth == 1 &&
                node_name_is(structure + name_start, name_length, "chosen"));
            ++offset;
            offset = (offset + 3U) & ~3U;
        } else if (token == FDT_END_NODE) {
            if (depth < 0)
                return 0;
            --depth;
        } else if (token == FDT_PROP) {
            if (depth < 0 || offset + 8U > struct_size)
                return 0;
            uint32_t length = read_be32(structure + offset);
            uint32_t name_offset = read_be32(structure + offset + 4U);
            offset += 8U;
            if (length > struct_size - offset || name_offset >= strings_size)
                return 0;
            if (chosen[depth] &&
                fdt_string_is(strings, strings_size, name_offset, property)) {
                if (length == 4U)
                    *value = read_be32(structure + offset);
                else if (length == 8U)
                    *value = read_be64(structure + offset);
                else
                    return 0;
                return 1;
            }
            offset += length;
            offset = (offset + 3U) & ~3U;
        } else if (token == FDT_NOP) {
            continue;
        } else if (token == FDT_END) {
            break;
        } else {
            return 0;
        }
    }
    return 0;
}
