#include "tap.h"
#include "render.h"
#include "pages.h"

static char top[RENDER_BUF];
static char bottom[RENDER_BUF];

/* A plausible board: 42.0 C, the rails at their nominal voltages, the pot
 * about two thirds up. */
static readings_t healthy(void)
{
    readings_t r = {
        .temperature_mc = 41999,
        .temp_min_mc    = 41200,
        .temp_max_mc    = 44100,
        .vccint_uv      = 851000,
        .vccaux_uv      = 1800000,
        .vccbram_uv     = 850000,
        .pot_uv         = 623000,
    };
    return r;
}

TEST(the_top_row_shows_the_temperature_to_a_tenth)
{
    readings_t r = healthy();
    render_top(top, sizeof top, &r);
    ASSERT_STR_EQ(top, "Temp      42.0 C");
}

TEST(the_top_row_is_exactly_the_width_of_the_panel)
{
    /* Anything shorter leaves the previous frame's characters behind. */
    readings_t r = healthy();
    render_top(top, sizeof top, &r);
    ASSERT_EQ_INT(strlen(top), LCD_COLS);
}

TEST(the_top_row_holds_its_width_for_a_negative_temperature)
{
    readings_t r = healthy();
    r.temperature_mc = -10500;
    render_top(top, sizeof top, &r);
    ASSERT_EQ_INT(strlen(top), LCD_COLS);
    ASSERT_STR_EQ(top, "Temp     -10.5 C");
}

TEST(the_top_row_holds_its_width_for_the_impossible_reading)
{
    /* -280.2 C is what raw zero converts to. It should never be displayed,
     * because sysmon_locate rejects that window -- but if it ever is, it must
     * not push the layout apart. */
    readings_t r = healthy();
    r.temperature_mc = -280231;
    render_top(top, sizeof top, &r);
    ASSERT_EQ_INT(strlen(top), LCD_COLS);
}

TEST(the_vccint_page_names_the_rail_and_its_voltage)
{
    readings_t r = healthy();
    render_bottom(bottom, sizeof bottom, &r, PAGE_VCCINT);
    ASSERT_STR_EQ(bottom, "VCCINT    0.851V");
}

TEST(the_vccaux_page_shows_the_one_point_eight_volt_rail)
{
    readings_t r = healthy();
    render_bottom(bottom, sizeof bottom, &r, PAGE_VCCAUX);
    ASSERT_STR_EQ(bottom, "VCCAUX    1.800V");
}

TEST(the_bram_rail_page_shows_its_own_reading)
{
    readings_t r = healthy();
    render_bottom(bottom, sizeof bottom, &r, PAGE_VCCBRAM);
    ASSERT_STR_EQ(bottom, "VBRAM     0.850V");
}

TEST(the_pot_page_shows_the_external_channel)
{
    readings_t r = healthy();
    render_bottom(bottom, sizeof bottom, &r, PAGE_POT);
    ASSERT_STR_EQ(bottom, "Pot       0.623V");
}

TEST(the_range_page_shows_both_extremes_the_macro_latched)
{
    readings_t r = healthy();
    render_bottom(bottom, sizeof bottom, &r, PAGE_TEMP_RANGE);
    ASSERT_STR_EQ(bottom, "Rng  41.2/ 44.1C");
}

TEST(every_page_fills_the_row)
{
    /* A page that rendered short would leave the previous page's tail
     * visible, which is exactly the confusion the pot is meant to dispel. */
    readings_t r = healthy();
    for (int p = 0; p < PAGE_COUNT; p++) {
        render_bottom(bottom, sizeof bottom, &r, p);
        ASSERT_EQ_INT(strlen(bottom), LCD_COLS);
    }
}

TEST(a_page_out_of_range_renders_rather_than_reading_past_its_table)
{
    /* page_select cannot produce this. The clamp is defence on a processor
     * with no memory protection and no way to report a crash. */
    readings_t r = healthy();
    render_bottom(bottom, sizeof bottom, &r, PAGE_COUNT + 3);
    ASSERT_EQ_INT(strlen(bottom), LCD_COLS);
    render_bottom(bottom, sizeof bottom, &r, -1);
    ASSERT_EQ_INT(strlen(bottom), LCD_COLS);
}

TEST(a_rail_at_full_scale_still_fits_its_field)
{
    readings_t r = healthy();
    r.vccint_uv = 2999954;
    render_bottom(bottom, sizeof bottom, &r, PAGE_VCCINT);
    ASSERT_EQ_INT(strlen(bottom), LCD_COLS);
    ASSERT_STR_EQ(bottom, "VCCINT    3.000V");
}

TEST(the_sysmon_fault_says_which_part_failed)
{
    /* With no UART this is the entire error report, so it has to name the
     * thing that went wrong rather than just refusing to show numbers. */
    render_sysmon_fault(top, bottom, RENDER_BUF);
    ASSERT_EQ_INT(strlen(top), LCD_COLS);
    ASSERT_EQ_INT(strlen(bottom), LCD_COLS);
    ASSERT_TRUE(strstr(top, "SYSMON") != NULL);
}

TEST(rendering_refuses_a_buffer_too_small_for_a_row)
{
    char small[4] = { 'x', 'x', 'x', 0 };
    readings_t r = healthy();
    render_top(small, sizeof small, &r);
    ASSERT_STR_EQ(small, "");
    render_bottom(small, sizeof small, &r, PAGE_VCCINT);
    ASSERT_STR_EQ(small, "");
}

TAP_MAIN_BEGIN
    RUN(the_top_row_shows_the_temperature_to_a_tenth);
    RUN(the_top_row_is_exactly_the_width_of_the_panel);
    RUN(the_top_row_holds_its_width_for_a_negative_temperature);
    RUN(the_top_row_holds_its_width_for_the_impossible_reading);
    RUN(the_vccint_page_names_the_rail_and_its_voltage);
    RUN(the_vccaux_page_shows_the_one_point_eight_volt_rail);
    RUN(the_bram_rail_page_shows_its_own_reading);
    RUN(the_pot_page_shows_the_external_channel);
    RUN(the_range_page_shows_both_extremes_the_macro_latched);
    RUN(every_page_fills_the_row);
    RUN(a_page_out_of_range_renders_rather_than_reading_past_its_table);
    RUN(a_rail_at_full_scale_still_fits_its_field);
    RUN(the_sysmon_fault_says_which_part_failed);
    RUN(rendering_refuses_a_buffer_too_small_for_a_row);
TAP_MAIN_END
