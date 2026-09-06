#include "tap.h"
#include "pages.h"

/* Full scale is 65536 codes over PAGE_COUNT bands. */
#define BAND (65536 / PAGE_COUNT)

TEST(a_pot_at_the_bottom_selects_the_first_page)
{
    ASSERT_EQ_INT(page_select(-1, 0), PAGE_VCCINT);
}

TEST(a_pot_at_full_scale_selects_the_last_page)
{
    ASSERT_EQ_INT(page_select(-1, 65535), PAGE_COUNT - 1);
}

TEST(each_band_selects_its_own_page_from_a_cold_start)
{
    for (int p = 0; p < PAGE_COUNT; p++) {
        uint16_t middle = (uint16_t)(p * BAND + BAND / 2);
        ASSERT_EQ_INT(page_select(-1, middle), p);
    }
}

TEST(the_page_holds_while_the_pot_sits_just_past_a_boundary)
{
    /* This is the whole point of the hysteresis. A pot resting on a boundary
     * moves by a code or two on ADC noise; without this it would flip pages
     * several times a second. */
    uint16_t just_over = (uint16_t)(BAND + 10);
    ASSERT_EQ_INT(page_select(PAGE_VCCINT, just_over), PAGE_VCCINT);
}

TEST(the_page_holds_while_the_pot_sits_just_below_a_boundary)
{
    uint16_t just_under = (uint16_t)(BAND - 10);
    ASSERT_EQ_INT(page_select(PAGE_VCCAUX, just_under), PAGE_VCCAUX);
}

TEST(the_page_follows_the_pot_past_the_boundary_plus_the_margin)
{
    uint16_t clear_of_it = (uint16_t)(BAND + PAGE_HYSTERESIS + 1);
    ASSERT_EQ_INT(page_select(PAGE_VCCINT, clear_of_it), PAGE_VCCAUX);
}

TEST(the_page_follows_the_pot_back_down_past_the_margin)
{
    uint16_t clear_of_it = (uint16_t)(BAND - PAGE_HYSTERESIS - 1);
    ASSERT_EQ_INT(page_select(PAGE_VCCAUX, clear_of_it), PAGE_VCCINT);
}

TEST(a_sweep_of_the_pot_visits_every_page_in_order)
{
    /* Turning the knob from one end to the other has to pass through all
     * five, or a page is unreachable and the operator cannot tell whether it
     * is the pot or the application that is stuck. */
    int page = -1, seen = 0, last = -1;
    for (uint32_t raw = 0; raw < 65536; raw += 16) {
        page = page_select(page, (uint16_t)raw);
        if (page != last) {
            ASSERT_EQ_INT(page, last + 1);
            last = page;
            seen++;
        }
    }
    ASSERT_EQ_INT(seen, PAGE_COUNT);
}

TEST(a_sweep_back_down_visits_every_page_in_reverse)
{
    int page = PAGE_COUNT - 1, last = PAGE_COUNT - 1, seen = 1;
    for (int32_t raw = 65535; raw >= 0; raw -= 16) {
        page = page_select(page, (uint16_t)raw);
        if (page != last) {
            ASSERT_EQ_INT(page, last - 1);
            last = page;
            seen++;
        }
    }
    ASSERT_EQ_INT(seen, PAGE_COUNT);
}

TEST(a_page_out_of_range_is_treated_as_no_page_yet)
{
    /* main() passes -1 on the first call, before the pot has been read. Any
     * other out-of-range value takes the same path rather than being used as
     * an index. */
    ASSERT_EQ_INT(page_select(99, 0), PAGE_VCCINT);
    ASSERT_EQ_INT(page_select(-7, 65535), PAGE_COUNT - 1);
}

TAP_MAIN_BEGIN
    RUN(a_pot_at_the_bottom_selects_the_first_page);
    RUN(a_pot_at_full_scale_selects_the_last_page);
    RUN(each_band_selects_its_own_page_from_a_cold_start);
    RUN(the_page_holds_while_the_pot_sits_just_past_a_boundary);
    RUN(the_page_holds_while_the_pot_sits_just_below_a_boundary);
    RUN(the_page_follows_the_pot_past_the_boundary_plus_the_margin);
    RUN(the_page_follows_the_pot_back_down_past_the_margin);
    RUN(a_sweep_of_the_pot_visits_every_page_in_order);
    RUN(a_sweep_back_down_visits_every_page_in_reverse);
    RUN(a_page_out_of_range_is_treated_as_no_page_yet);
TAP_MAIN_END
