#include "tap.h"
#include "fake_mmio.h"
#include "grove_lcd.h"

#define BASE 0x40800000u

static axi_iic_t iic;
static grove_lcd_t lcd;

static void bus_healthy(void)
{
    fake_set(BASE, IIC_SR, 0);
    fake_set(BASE, IIC_ISR, 0);
}

/* The panel only ever sees pairs: a framing byte and a payload. Recovering
 * them from the FIFO writes is how these tests read the wire. */
static int fifo_bytes(uint8_t *out, int cap)
{
    int n = 0;
    for (size_t i = 0; i < fake.write_count && n < cap; i++)
        if (fake.writes[i].off == IIC_TX_FIFO)
            out[n++] = (uint8_t)(fake.writes[i].value & 0xFFu);
    return n;
}

/* The index of the nth byte sent with the command framing byte before it. */
static int command_at(int index, uint8_t *out)
{
    uint8_t b[256];
    int n = fifo_bytes(b, 256);
    int seen = 0;
    /* Each transaction is address, framing, payload. */
    for (int i = 0; i + 2 < n; i++) {
        if (b[i + 1] == LCD_CTRL_CMD && (b[i] & 0xFEu) == (LCD_ADDR << 1)) {
            if (seen == index) { *out = b[i + 2]; return 1; }
            seen++;
            i += 2;
        }
    }
    return 0;
}

static int command_count(void)
{
    uint8_t b[256];
    int n = fifo_bytes(b, 256), seen = 0;
    for (int i = 0; i + 2 < n; i++) {
        if (b[i + 1] == LCD_CTRL_CMD && (b[i] & 0xFEu) == (LCD_ADDR << 1)) {
            seen++;
            i += 2;
        }
    }
    return seen;
}

static void init_lcd(void)
{
    fake_reset();
    bus_healthy();
    axi_iic_init(&iic, BASE);
    grove_lcd_init(&lcd, &iic, LCD_DEFAULT_CONTRAST);
}

TEST(init_enters_the_extended_instruction_set_before_touching_contrast)
{
    /* The booster, follower and contrast registers do not exist in the normal
     * instruction set. Writing 0x70|n there sets the cursor somewhere instead
     * and the panel comes up initialised and blank. */
    uint8_t c0, c1, c2;
    init_lcd();

    ASSERT_TRUE(command_at(0, &c0));
    ASSERT_TRUE(command_at(1, &c1));
    ASSERT_TRUE(command_at(2, &c2));
    ASSERT_EQ_INT(c0, 0x38);   /* function set, 2 line, IS = 0 */
    ASSERT_EQ_INT(c1, 0x39);   /* function set, IS = 1: extended */
    ASSERT_EQ_INT(c2, 0x14);   /* internal oscillator, 1/5 bias */
}

TEST(init_programs_the_contrast_it_was_asked_for)
{
    /* Contrast splits across two commands: the low four bits with 0x70 and
     * the high two with the booster control. Sending only one of them gives
     * a panel that is faintly on, which reads as a wiring fault. */
    uint8_t low, high;
    init_lcd();

    ASSERT_TRUE(command_at(3, &low));
    ASSERT_TRUE(command_at(4, &high));
    ASSERT_EQ_INT(low, 0x70 | (LCD_DEFAULT_CONTRAST & 0x0F));
    ASSERT_EQ_INT(high, 0x50 | 0x04 | ((LCD_DEFAULT_CONTRAST >> 4) & 0x03));
}

TEST(init_turns_the_follower_on_after_the_booster)
{
    uint8_t follower;
    init_lcd();
    ASSERT_TRUE(command_at(5, &follower));
    ASSERT_EQ_INT(follower, 0x6C);
}

TEST(init_waits_for_the_booster_to_settle)
{
    /* More than 200 ms, and this is not a margin to trim: a shorter wait
     * produces a panel that accepts every command and displays nothing. */
    init_lcd();
    ASSERT_TRUE(fake.delay_total_us >= 200000u);
}

TEST(init_leaves_the_extended_instruction_set_before_enabling_the_display)
{
    /* 0x0C means display-on only while IS = 0. */
    uint8_t back, display;
    init_lcd();

    ASSERT_TRUE(command_at(6, &back));
    ASSERT_TRUE(command_at(7, &display));
    ASSERT_EQ_INT(back, 0x38);
    ASSERT_EQ_INT(display, 0x0C);
}

TEST(init_clears_the_panel_and_sets_the_entry_mode)
{
    uint8_t clear, entry;
    init_lcd();

    ASSERT_TRUE(command_at(8, &clear));
    ASSERT_TRUE(command_at(9, &entry));
    ASSERT_EQ_INT(clear, 0x01);
    ASSERT_EQ_INT(entry, 0x06);
    ASSERT_EQ_INT(command_count(), 10);
}

TEST(clear_waits_for_the_panel_to_finish)
{
    /* Clear is the slowest command the panel has. Sending the next byte
     * before it completes loses that byte silently. */
    init_lcd();
    uint32_t before = fake.delay_total_us;
    grove_lcd_clear(&lcd);
    ASSERT_TRUE(fake.delay_total_us > before);
}

TEST(set_cursor_addresses_the_second_row_through_the_ddram_offset)
{
    /* The second row is not the 17th character: it starts at DDRAM 0x40. */
    uint8_t cmd;
    init_lcd();
    fake_reset();
    bus_healthy();

    grove_lcd_set_cursor(&lcd, 0, 1);
    ASSERT_TRUE(command_at(0, &cmd));
    ASSERT_EQ_INT(cmd, 0x80 | 0x40);
}

TEST(set_cursor_addresses_a_column_on_the_first_row)
{
    uint8_t cmd;
    init_lcd();
    fake_reset();
    bus_healthy();

    grove_lcd_set_cursor(&lcd, 5, 0);
    ASSERT_TRUE(command_at(0, &cmd));
    ASSERT_EQ_INT(cmd, 0x80 | 5);
}

TEST(write_sends_each_character_with_the_data_framing_byte)
{
    uint8_t b[64];
    init_lcd();
    fake_reset();
    bus_healthy();

    grove_lcd_write(&lcd, "Hi");

    int n = fifo_bytes(b, 64);
    ASSERT_EQ_INT(n, 6);                       /* two transactions of three */
    ASSERT_EQ_INT(b[1], LCD_CTRL_DATA);
    ASSERT_EQ_INT(b[2], 'H');
    ASSERT_EQ_INT(b[4], LCD_CTRL_DATA);
    ASSERT_EQ_INT(b[5], 'i');
}

TEST(write_row_pads_to_the_full_width)
{
    /* The panel does not clear to end of line. A shorter string than the last
     * frame leaves the tail of the old one on the glass, which turns
     * "1.800V" following "0.851V" into "1.800V" plus a stray character. */
    uint8_t b[128];
    init_lcd();
    fake_reset();
    bus_healthy();

    grove_lcd_write_row(&lcd, 0, "Hi");

    int n = fifo_bytes(b, 128);
    /* one set-cursor transaction of three, then 16 character transactions */
    ASSERT_EQ_INT(n, 3 + 16 * 3);
    ASSERT_EQ_INT(b[5], 'H');
    ASSERT_EQ_INT(b[8], 'i');
    ASSERT_EQ_INT(b[11], ' ');
    ASSERT_EQ_INT(b[3 + 15 * 3 + 2], ' ');
}

TEST(write_row_truncates_a_string_too_long_for_the_panel)
{
    /* Sending a 17th character wraps it onto the other row, so a formatting
     * mistake on one line silently corrupts the other. */
    uint8_t b[128];
    init_lcd();
    fake_reset();
    bus_healthy();

    grove_lcd_write_row(&lcd, 0, "0123456789ABCDEFGHIJ");

    int n = fifo_bytes(b, 128);
    ASSERT_EQ_INT(n, 3 + 16 * 3);
    ASSERT_EQ_INT(b[3 + 15 * 3 + 2], 'F');
}

TEST(a_nack_during_init_is_reported_rather_than_ignored)
{
    fake_reset();
    fake_set(BASE, IIC_SR, 0);
    fake_set(BASE, IIC_ISR, IIC_ISR_TX_ERROR);
    axi_iic_init(&iic, BASE);

    ASSERT_EQ_INT(grove_lcd_init(&lcd, &iic, LCD_DEFAULT_CONTRAST), IIC_ENACK);
}

TAP_MAIN_BEGIN
    RUN(init_enters_the_extended_instruction_set_before_touching_contrast);
    RUN(init_programs_the_contrast_it_was_asked_for);
    RUN(init_turns_the_follower_on_after_the_booster);
    RUN(init_waits_for_the_booster_to_settle);
    RUN(init_leaves_the_extended_instruction_set_before_enabling_the_display);
    RUN(init_clears_the_panel_and_sets_the_entry_mode);
    RUN(clear_waits_for_the_panel_to_finish);
    RUN(set_cursor_addresses_the_second_row_through_the_ddram_offset);
    RUN(set_cursor_addresses_a_column_on_the_first_row);
    RUN(write_sends_each_character_with_the_data_framing_byte);
    RUN(write_row_pads_to_the_full_width);
    RUN(write_row_truncates_a_string_too_long_for_the_panel);
    RUN(a_nack_during_init_is_reported_rather_than_ignored);
TAP_MAIN_END
