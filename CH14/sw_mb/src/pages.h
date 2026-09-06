/* Which of the SYSMON's readings the second line shows, chosen by the pot.
 *
 * A 16x2 panel holds 32 characters and the SYSMON has more to say than that,
 * so the pot picks the page. That also makes the pot do real work rather than
 * being a number on a screen, and gives the operator a way to prove the whole
 * chain -- ADC to processor to I2C to glass -- is alive, by turning a knob.
 *
 * HYSTERESIS IS NOT A REFINEMENT HERE. Bands straight off the ADC code mean a
 * pot resting on a boundary flips the page on ADC noise, several times a
 * second, which is unreadable. The pot has to move PAST a boundary by a
 * margin before the page follows it. */
#ifndef PAGES_H
#define PAGES_H

#include <stdint.h>

typedef enum {
    PAGE_VCCINT = 0,
    PAGE_VCCAUX,
    PAGE_VCCBRAM,
    PAGE_POT,
    PAGE_TEMP_RANGE,
    PAGE_COUNT
} page_t;

/* One fiftieth of full scale: comfortably more than the couple of codes the
 * averaged reading moves by, and far less than a band, so the knob still
 * feels like it has five detents rather than five sticky ones. */
#define PAGE_HYSTERESIS 1310

/* The page to show, given the page currently shown and the latest pot
 * reading. `current` outside 0..PAGE_COUNT-1 is treated as "none yet". */
int page_select(int current, uint16_t pot_raw);

#endif /* PAGES_H */
