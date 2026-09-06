/* The one boundary between these drivers and the machine.
 *
 * Everything below this line is register traffic and timing; everything above
 * it is logic that can be reasoned about and tested on a workstation. Keeping
 * that split honest is why the drivers never call Xil_In32 directly. */
#ifndef MMIO_H
#define MMIO_H

#include <stdint.h>

#ifdef MB_HOST_TEST

uint32_t mmio_read32(uintptr_t base, uint32_t off);
void     mmio_write32(uintptr_t base, uint32_t off, uint32_t value);
void     plat_delay_us(uint32_t us);

#else

#include "xil_io.h"

static inline uint32_t mmio_read32(uintptr_t base, uint32_t off)
{
    return Xil_In32((UINTPTR)(base + off));
}

static inline void mmio_write32(uintptr_t base, uint32_t off, uint32_t value)
{
    Xil_Out32((UINTPTR)(base + off), value);
}

void plat_delay_us(uint32_t us);

#endif /* MB_HOST_TEST */

#endif /* MMIO_H */
