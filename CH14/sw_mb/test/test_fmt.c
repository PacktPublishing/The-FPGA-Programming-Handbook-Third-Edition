#include "tap.h"
#include "fmt.h"

static char b[32];

TEST(renders_a_temperature_to_a_tenth_of_a_degree)
{
    ASSERT_TRUE(fmt_fixed(b, sizeof b, 42345, 3, 1) > 0);
    ASSERT_STR_EQ(b, "42.3");
}

TEST(renders_a_supply_voltage_to_a_millivolt)
{
    ASSERT_TRUE(fmt_fixed(b, sizeof b, 851000, 6, 3) > 0);
    ASSERT_STR_EQ(b, "0.851");
}

TEST(rounds_rather_than_truncating)
{
    /* 0.8509 V shown to three places is 0.851. Truncating would show 0.850,
     * which is wrong by a whole count in the digit being watched. */
    ASSERT_TRUE(fmt_fixed(b, sizeof b, 850900, 6, 3) > 0);
    ASSERT_STR_EQ(b, "0.851");
}

TEST(rounds_half_away_from_zero)
{
    ASSERT_TRUE(fmt_fixed(b, sizeof b, 42350, 3, 1) > 0);
    ASSERT_STR_EQ(b, "42.4");
}

TEST(rounding_can_carry_into_the_integer_part)
{
    /* 41.96 to one place is 42.0, not 41.10 or 42 with nothing after it. */
    ASSERT_TRUE(fmt_fixed(b, sizeof b, 41960, 3, 1) > 0);
    ASSERT_STR_EQ(b, "42.0");
}

TEST(keeps_leading_zeros_in_the_fraction)
{
    /* 1.005 must not render as 1.5. */
    ASSERT_TRUE(fmt_fixed(b, sizeof b, 1005000, 6, 3) > 0);
    ASSERT_STR_EQ(b, "1.005");
}

TEST(renders_a_negative_value)
{
    ASSERT_TRUE(fmt_fixed(b, sizeof b, -1500, 3, 1) > 0);
    ASSERT_STR_EQ(b, "-1.5");
}

TEST(renders_a_negative_value_below_one)
{
    /* The sign has to survive an integer part of zero. */
    ASSERT_TRUE(fmt_fixed(b, sizeof b, -500, 3, 1) > 0);
    ASSERT_STR_EQ(b, "-0.5");
}

TEST(renders_with_no_decimal_places_at_all)
{
    ASSERT_TRUE(fmt_fixed(b, sizeof b, 42345, 3, 0) > 0);
    ASSERT_STR_EQ(b, "42");
}

TEST(renders_the_coldest_reading_the_sysmon_can_produce)
{
    /* Raw zero is -280.231 C, and it is the value the display shows when the
     * SYSMON is not converting, so it has to render rather than overflow. */
    ASSERT_TRUE(fmt_fixed(b, sizeof b, -280231, 3, 1) > 0);
    ASSERT_STR_EQ(b, "-280.2");
}

TEST(refuses_to_write_past_the_end_of_the_buffer)
{
    /* A 16x2 panel gives no room for a surprise, and there is no console to
     * report a smashed stack on. */
    char small[4];
    ASSERT_EQ_INT(fmt_fixed(small, sizeof small, 851000, 6, 3), -1);
    ASSERT_EQ_INT(small[0], 0);
}

TEST(pad_fills_a_short_string_to_the_field_width)
{
    ASSERT_TRUE(fmt_pad(b, sizeof b, "Hi", 6) > 0);
    ASSERT_STR_EQ(b, "Hi    ");
}

TEST(pad_truncates_a_string_longer_than_the_field)
{
    ASSERT_TRUE(fmt_pad(b, sizeof b, "0123456789", 4) > 0);
    ASSERT_STR_EQ(b, "0123");
}

TEST(pad_left_right_aligns_so_a_decimal_point_stays_put)
{
    /* A voltage whose integer part changes width would otherwise walk the
     * decimal point across the panel as the value crosses 10. */
    ASSERT_TRUE(fmt_pad_left(b, sizeof b, "0.851", 7) > 0);
    ASSERT_STR_EQ(b, "  0.851");
}

TEST(pad_refuses_a_field_wider_than_the_buffer)
{
    char small[4];
    ASSERT_EQ_INT(fmt_pad(small, sizeof small, "Hi", 8), -1);
}

TAP_MAIN_BEGIN
    RUN(renders_a_temperature_to_a_tenth_of_a_degree);
    RUN(renders_a_supply_voltage_to_a_millivolt);
    RUN(rounds_rather_than_truncating);
    RUN(rounds_half_away_from_zero);
    RUN(rounding_can_carry_into_the_integer_part);
    RUN(keeps_leading_zeros_in_the_fraction);
    RUN(renders_a_negative_value);
    RUN(renders_a_negative_value_below_one);
    RUN(renders_with_no_decimal_places_at_all);
    RUN(renders_the_coldest_reading_the_sysmon_can_produce);
    RUN(refuses_to_write_past_the_end_of_the_buffer);
    RUN(pad_fills_a_short_string_to_the_field_width);
    RUN(pad_truncates_a_string_longer_than_the_field);
    RUN(pad_left_right_aligns_so_a_decimal_point_stays_put);
    RUN(pad_refuses_a_field_wider_than_the_buffer);
TAP_MAIN_END
