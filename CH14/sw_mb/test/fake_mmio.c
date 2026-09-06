#include "fake_mmio.h"
#include "mmio.h"

#include <stdio.h>
#include <string.h>

fake_mmio_t fake;

void fake_reset(void)
{
    memset(&fake, 0, sizeof fake);
}

void fake_set(uintptr_t base, uint32_t off, uint32_t value)
{
    for (size_t i = 0; i < fake.read_count; i++) {
        if (fake.reads[i].base == base && fake.reads[i].off == off) {
            fake.reads[i].value = value;
            return;
        }
    }
    if (fake.read_count >= FAKE_MAX_ENTRIES) {
        printf("    fake_mmio: read table full\n");
        return;
    }
    fake.reads[fake.read_count].base = base;
    fake.reads[fake.read_count].off = off;
    fake.reads[fake.read_count].value = value;
    fake.read_count++;
}

uint32_t fake_written(size_t index)
{
    return index < fake.write_count ? fake.writes[index].value : 0xDEADBEEFu;
}

uint32_t fake_written_off(size_t index)
{
    return index < fake.write_count ? fake.writes[index].off : 0xFFFFFFFFu;
}

uint32_t mmio_read32(uintptr_t base, uint32_t off)
{
    for (size_t i = 0; i < fake.read_count; i++)
        if (fake.reads[i].base == base && fake.reads[i].off == off)
            return fake.reads[i].value;
    fake.unmapped_reads++;
    return 0;
}

void mmio_write32(uintptr_t base, uint32_t off, uint32_t value)
{
    if (fake.write_count < FAKE_MAX_ENTRIES) {
        fake.writes[fake.write_count].base = base;
        fake.writes[fake.write_count].off = off;
        fake.writes[fake.write_count].value = value;
    }
    fake.write_count++;
}

void plat_delay_us(uint32_t us)
{
    fake.delay_total_us += us;
    if (fake.delay_count < FAKE_MAX_ENTRIES)
        fake.delays[fake.delay_count] = us;
    fake.delay_count++;
}
