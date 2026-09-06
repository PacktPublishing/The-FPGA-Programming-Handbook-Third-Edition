/* Turning readings into two rows of sixteen characters.
 *
 * Kept apart from main.c and from the panel driver because it is the one part
 * of the display that has an answer a test can check. Nothing here touches a
 * register, so every layout decision below is verified on a workstation
 * rather than by squinting at a panel. */
#ifndef RENDER_H
#define RENDER_H

#include <stddef.h>
#include <stdint.h>

#include "grove_lcd.h"   /* LCD_COLS */

/* Room for a full row and its terminator. */
#define RENDER_BUF (LCD_COLS + 1)

typedef struct {
    int32_t  temperature_mc;
    int32_t  temp_min_mc;
    int32_t  temp_max_mc;
    uint32_t vccint_uv;
    uint32_t vccaux_uv;
    uint32_t vccbram_uv;
    uint32_t pot_uv;
} readings_t;

/* Both write exactly LCD_COLS characters plus a terminator, so `cap` must be
 * at least RENDER_BUF. Anything shorter would leave the previous frame's tail
 * on the glass, which the panel has no way to clear on its own. */
void render_top(char *out, size_t cap, const readings_t *r);
void render_bottom(char *out, size_t cap, const readings_t *r, int page);

/* What to show when the SYSMON could not be found. This is the closest thing
 * this design has to an error message: with no UART, the panel is where a
 * failure has to be reported or it is not reported at all. */
void render_sysmon_fault(char *top, char *bottom, size_t cap);

#endif /* RENDER_H */
