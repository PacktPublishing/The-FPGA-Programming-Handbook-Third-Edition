#include "grove_lcd.h"
#include "mmio.h"
#include "fmt.h"

/* Every transfer to this panel is two bytes: a framing byte saying what
 * follows, then the command or character itself. */
static iic_status_t send(grove_lcd_t *lcd, uint8_t control, uint8_t value)
{
    const uint8_t pair[2] = { control, value };
    return axi_iic_write(lcd->iic, LCD_ADDR, pair, 2);
}

static iic_status_t cmd(grove_lcd_t *lcd, uint8_t c)
{
    return send(lcd, LCD_CTRL_CMD, c);
}

/* The initialisation sequence, in the order it has to happen.
 *
 * CH10 arrived at this empirically and it is not the datasheet's. The two
 * things that are easy to get wrong and impossible to diagnose without a
 * scope are marked below. */
iic_status_t grove_lcd_init(grove_lcd_t *lcd, axi_iic_t *iic, uint8_t contrast)
{
    iic_status_t s;

    lcd->iic = iic;

    plat_delay_us(50000);                        /* panel power-on */

    s = cmd(lcd, 0x38);                          /* 8-bit, 2 line, IS = 0 */
    if (s != IIC_OK) return s;

    /* IS = 1. The booster, follower and contrast registers do not exist
     * outside the extended instruction set -- writing them with IS = 0 sets
     * the cursor somewhere instead, and the panel initialises cleanly and
     * stays blank. */
    s = cmd(lcd, 0x39);                          if (s != IIC_OK) return s;
    s = cmd(lcd, 0x14);                          /* oscillator, 1/5 bias */
    if (s != IIC_OK) return s;

    /* Contrast is split across two registers: the low four bits here... */
    s = cmd(lcd, (uint8_t)(0x70u | (contrast & 0x0Fu)));
    if (s != IIC_OK) return s;
    /* ...and the high two alongside the booster enable. Sending only one
     * leaves the panel faintly lit, which reads as a wiring fault. */
    s = cmd(lcd, (uint8_t)(0x50u | 0x04u | ((contrast >> 4) & 0x03u)));
    if (s != IIC_OK) return s;

    s = cmd(lcd, 0x6C);                          /* follower on, amp ratio */
    if (s != IIC_OK) return s;

    /* MORE THAN 200 ms, and not a margin to trim. The booster and follower
     * charge pumps need this long to come up; a shorter wait gives a panel
     * that acknowledges every byte and displays nothing. */
    plat_delay_us(300000);

    s = cmd(lcd, 0x38);                          /* back to IS = 0 */
    if (s != IIC_OK) return s;
    s = cmd(lcd, 0x0C);                          /* display on, no cursor */
    if (s != IIC_OK) return s;

    s = grove_lcd_clear(lcd);                    if (s != IIC_OK) return s;
    return cmd(lcd, 0x06);                       /* entry mode: increment */
}

iic_status_t grove_lcd_clear(grove_lcd_t *lcd)
{
    iic_status_t s = cmd(lcd, 0x01);
    /* Clear is the slowest command the panel has. The next byte sent before
     * it finishes is dropped without complaint. */
    plat_delay_us(2000);
    return s;
}

iic_status_t grove_lcd_set_cursor(grove_lcd_t *lcd, uint8_t col, uint8_t row)
{
    /* The second row is not the seventeenth character: DDRAM jumps to 0x40. */
    uint8_t address = (uint8_t)(col | (row ? 0x40u : 0x00u));
    return cmd(lcd, (uint8_t)(0x80u | address));
}

iic_status_t grove_lcd_write(grove_lcd_t *lcd, const char *text)
{
    for (const char *p = text; *p != '\0'; p++) {
        iic_status_t s = send(lcd, LCD_CTRL_DATA, (uint8_t)*p);
        if (s != IIC_OK)
            return s;
    }
    return IIC_OK;
}

iic_status_t grove_lcd_write_row(grove_lcd_t *lcd, uint8_t row, const char *text)
{
    char padded[LCD_COLS + 1];
    iic_status_t s;

    /* Padding is not cosmetic. The panel has no clear-to-end-of-line, so a
     * string shorter than the last frame's leaves that frame's tail on the
     * glass -- "1.800V" after "0.851V" would show a stray character. The same
     * call truncates anything too long, which would otherwise wrap onto the
     * other row and corrupt a line this call never touched. */
    if (fmt_pad(padded, sizeof padded, text, LCD_COLS) < 0)
        return IIC_EINVAL;

    s = grove_lcd_set_cursor(lcd, 0, row);
    if (s != IIC_OK)
        return s;
    return grove_lcd_write(lcd, padded);
}
