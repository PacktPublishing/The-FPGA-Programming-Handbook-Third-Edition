#include "pages.h"

/* Full scale divided into one band per page. 65536 rather than 65535 so the
 * bands are equal; the top code lands in the last one either way. */
#define BAND ((int32_t)(65536 / PAGE_COUNT))

int page_select(int current, uint16_t pot_raw)
{
    int32_t raw = (int32_t)pot_raw;

    /* The band the pot is in, ignoring where it was. */
    int32_t band = raw / BAND;
    if (band >= PAGE_COUNT)
        band = PAGE_COUNT - 1;          /* the last band is one code wider */

    /* No page yet -- main() starts at -1, before the pot has been read once.
     * Anything else out of range is treated the same way rather than used as
     * an index. */
    if (current < 0 || current >= PAGE_COUNT)
        return (int)band;

    if (band == current)
        return current;

    /* Hold the current page until the pot is clear of the boundary by the
     * margin. Only the boundary being crossed gets the margin: the far edge
     * of the current band is someone else's boundary and widening both would
     * let the page lag two bands behind the knob. */
    int32_t lower = (int32_t)current * BAND;
    int32_t upper = lower + BAND;
    if (current > 0)
        lower -= PAGE_HYSTERESIS;
    if (current < PAGE_COUNT - 1)
        upper += PAGE_HYSTERESIS;

    if (raw >= lower && raw < upper)
        return current;

    /* Move one page at a time. A pot swept quickly between polls would
     * otherwise jump bands, and the display would skip pages that the
     * operator can see the knob passing through. */
    return band > current ? current + 1 : current - 1;
}
