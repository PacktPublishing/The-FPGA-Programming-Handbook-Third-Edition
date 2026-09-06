/* The parts that exist only on the board.
 *
 * Compiled by build_app.py and never by the host test build, which supplies
 * its own recording version of plat_delay_us from test/fake_mmio.c. */
#include "mmio.h"
#include "plat.h"

/* mcycle rather than a calibrated empty loop.
 *
 * An empty loop's duration is a property of the optimiser, and this code is
 * built -O2. The counter is a property of the hardware. C_USE_COUNTERS is 1
 * on this processor, so mcycle exists; mcycle rather than cycle because the
 * standalone application runs in machine mode, where mcycle is always
 * readable and needs no mcounteren permission. */
static inline uint32_t read_mcycle(void)
{
    uint32_t v;
    __asm__ volatile ("csrr %0, mcycle" : "=r" (v));
    return v;
}

void plat_delay_us(uint32_t us)
{
    /* The longest delay this application asks for is the panel's 300 ms
     * booster settle: 30 million cycles, comfortably inside 32 bits. The
     * unsigned subtraction below is also correct across a counter wrap, which
     * happens every 43 seconds at 100 MHz and would otherwise turn one delay
     * in every few hundred into a 43-second stall. */
    uint32_t start = read_mcycle();
    uint32_t target = us * (PLAT_CPU_HZ / 1000000u);
    while ((read_mcycle() - start) < target)
        ;
}
