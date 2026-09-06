/* The Grove 16x2 LCD: an AiP31068L, ST7032-compatible, at I2C address 0x3E.
 *
 * This is CH10's initialisation sequence, which was arrived at empirically
 * and is not the datasheet's. The differences matter:
 *
 *   - the extended instruction set (IS=1) has to be entered to reach the
 *     booster, follower and contrast registers at all, and left again before
 *     the display-control command means what it says;
 *   - the booster and follower need more than 200 ms to settle before the
 *     panel will show anything, and a shorter wait produces a display that
 *     initialises cleanly and stays blank;
 *   - contrast 0x38 with 1/5 bias is the combination that is actually
 *     readable on this panel. Contrast is not cosmetic here: get it wrong and
 *     the panel is indistinguishable from one that never received a byte. */
#ifndef GROVE_LCD_H
#define GROVE_LCD_H

#include <stdint.h>
#include "axi_iic.h"

#define LCD_ADDR      0x3Eu
#define LCD_COLS      16
#define LCD_ROWS      2

/* Framing byte prefixed to every transfer: 0x80 a command follows, 0x40 a
 * character follows. */
#define LCD_CTRL_CMD  0x80u
#define LCD_CTRL_DATA 0x40u

#define LCD_DEFAULT_CONTRAST 0x38u

typedef struct {
    axi_iic_t *iic;
} grove_lcd_t;

iic_status_t grove_lcd_init(grove_lcd_t *lcd, axi_iic_t *iic, uint8_t contrast);
iic_status_t grove_lcd_clear(grove_lcd_t *lcd);
iic_status_t grove_lcd_set_cursor(grove_lcd_t *lcd, uint8_t col, uint8_t row);
iic_status_t grove_lcd_write(grove_lcd_t *lcd, const char *text);

/* Write one whole row, padded to 16 characters. The panel does not clear to
 * end of line on its own, so a short string would leave the tail of the
 * previous frame visible. */
iic_status_t grove_lcd_write_row(grove_lcd_t *lcd, uint8_t row, const char *text);

#endif /* GROVE_LCD_H */
