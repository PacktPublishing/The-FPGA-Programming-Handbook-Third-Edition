#include "tap.h"
#include "fake_mmio.h"
#include "sysmon.h"

#define BASE 0x44A00000u

/* Readings a healthy AUP-ZU3 produces, used throughout. The raws are derived
 * from the conversions rather than measured, so a change to a conversion
 * constant that broke them would be caught by the conversion tests first. */
#define RAW_TEMP_42C   41463u   /* about 42.2 C */
#define RAW_VCCINT_850 18568u   /* about 0.850 V over the 3.0 V range */
#define RAW_VCCAUX_180 39321u   /* about 1.800 V over the 3.0 V range */

static void place_healthy_sysmon_at(uint32_t drp_base)
{
    fake_set(BASE, drp_base + 4 * DRP_TEMPERATURE, RAW_TEMP_42C);
    fake_set(BASE, drp_base + 4 * DRP_VCCINT,      RAW_VCCINT_850);
    fake_set(BASE, drp_base + 4 * DRP_VCCAUX,      RAW_VCCAUX_180);
}

TEST(locates_the_drp_window_where_this_hardware_puts_it)
{
    sysmon_t s;
    fake_reset();
    place_healthy_sysmon_at(0x1400u);

    sysmon_init(&s, BASE);
    ASSERT_EQ_INT(sysmon_locate(&s), SYSMON_OK);
    ASSERT_EQ_INT(s.drp_base, 0x1400u);
}

TEST(falls_back_to_the_vendor_drivers_window_when_that_is_the_live_one)
{
    sysmon_t s;
    fake_reset();
    place_healthy_sysmon_at(0x0400u);

    sysmon_init(&s, BASE);
    ASSERT_EQ_INT(sysmon_locate(&s), SYSMON_OK);
    ASSERT_EQ_INT(s.drp_base, 0x0400u);
}

TEST(rejects_a_window_whose_temperature_reads_zero)
{
    /* Raw zero is -280 C. No silicon is at -280 C, and a SYSMON that is
     * converting never reports it -- so this is the signature of reading an
     * address that decodes to nothing, which is the whole failure this
     * driver exists to avoid. */
    sysmon_t s;
    fake_reset();
    fake_set(BASE, 0x1400u + 4 * DRP_TEMPERATURE, 0);
    fake_set(BASE, 0x1400u + 4 * DRP_VCCINT,      RAW_VCCINT_850);
    fake_set(BASE, 0x1400u + 4 * DRP_VCCAUX,      RAW_VCCAUX_180);

    sysmon_init(&s, BASE);
    ASSERT_EQ_INT(sysmon_locate(&s), SYSMON_ENOTFOUND);
}

TEST(rejects_a_window_whose_supply_rails_disagree_with_the_board)
{
    /* A plausible temperature alone is not enough. Some other register could
     * happen to hold a value in the temperature band; two rails at the
     * voltages this board is built to could not. */
    sysmon_t s;
    fake_reset();
    fake_set(BASE, 0x1400u + 4 * DRP_TEMPERATURE, RAW_TEMP_42C);
    fake_set(BASE, 0x1400u + 4 * DRP_VCCINT,      RAW_VCCAUX_180);  /* 1.8 V */
    fake_set(BASE, 0x1400u + 4 * DRP_VCCAUX,      RAW_VCCINT_850);  /* 0.85 V */

    sysmon_init(&s, BASE);
    ASSERT_EQ_INT(sysmon_locate(&s), SYSMON_ENOTFOUND);
}

TEST(reports_not_found_when_every_window_is_silent)
{
    sysmon_t s;
    fake_reset();
    for (int i = 0; i < SYSMON_CANDIDATE_COUNT; i++) {
        fake_set(BASE, sysmon_drp_candidates[i] + 4 * DRP_TEMPERATURE, 0);
        fake_set(BASE, sysmon_drp_candidates[i] + 4 * DRP_VCCINT, 0);
        fake_set(BASE, sysmon_drp_candidates[i] + 4 * DRP_VCCAUX, 0);
    }

    sysmon_init(&s, BASE);
    ASSERT_EQ_INT(sysmon_locate(&s), SYSMON_ENOTFOUND);
}

TEST(prefers_the_measured_window_when_two_of_them_answer)
{
    /* The window aliases: CH13 found 0x1C00 mirroring 0x1400. If a candidate
     * ever aliases onto another, the order in sysmon_drp_candidates decides,
     * and the first entry is the one measured on this hardware. */
    sysmon_t s;
    fake_reset();
    place_healthy_sysmon_at(0x1400u);
    place_healthy_sysmon_at(0x0400u);

    sysmon_init(&s, BASE);
    ASSERT_EQ_INT(sysmon_locate(&s), SYSMON_OK);
    ASSERT_EQ_INT(s.drp_base, 0x1400u);
}

TEST(drp_read_addresses_one_word_per_drp_register)
{
    sysmon_t s;
    fake_reset();
    place_healthy_sysmon_at(0x1400u);
    fake_set(BASE, 0x1400u + 4 * DRP_VP_VN, 0x1234u);

    sysmon_init(&s, BASE);
    sysmon_locate(&s);
    ASSERT_EQ_INT(sysmon_drp_read(&s, DRP_VP_VN), 0x1234u);
}

TEST(drp_read_keeps_only_the_low_sixteen_bits)
{
    /* The result is left-justified in a 16-bit register inside a 32-bit
     * word. Whatever the upper half holds is not part of the measurement. */
    sysmon_t s;
    fake_reset();
    place_healthy_sysmon_at(0x1400u);
    fake_set(BASE, 0x1400u + 4 * DRP_VP_VN, 0xFFFF1234u);

    sysmon_init(&s, BASE);
    sysmon_locate(&s);
    ASSERT_EQ_INT(sysmon_drp_read(&s, DRP_VP_VN), 0x1234u);
}

TEST(temperature_converts_at_the_point_ug580_pins_down)
{
    /* UG580's UltraScale formula puts raw 41463 at 41999.45 millidegrees.
     * The running xilinx-ams driver agrees independently: 7.771514892
     * millidegrees per LSB and an offset of -280.2 C.
     *
     * The tolerance is 3 millidegrees, which is the worst-case error of the
     * integer scale constant anywhere in the range -- checked by evaluating
     * both forms over all 65536 codes, not assumed. The display shows tenths
     * of a degree, so this is about a hundredth of the last digit. */
    ASSERT_NEAR_INT(sysmon_raw_to_millicelsius(41463), 41999, 3);
}

TEST(temperature_raw_zero_is_the_impossible_reading)
{
    /* -280 C. This is why raw zero can be used as the signature of a dead or
     * mis-addressed converter rather than as a cold reading. */
    ASSERT_NEAR_INT(sysmon_raw_to_millicelsius(0), -280231, 3);
}

TEST(temperature_converts_a_cold_reading_below_zero)
{
    /* -10 C is raw ((-10 + 280.23087870) * 65536 / 509.3140064) = 34772.
     * Below the offset the result is negative, so the conversion cannot be
     * done in unsigned arithmetic however convenient the multiply is. */
    ASSERT_NEAR_INT(sysmon_raw_to_millicelsius(34772), -10000, 3);
}

TEST(supply_conversion_is_exact_at_full_scale)
{
    /* 65536 codes would be 3.000000 V; the register cannot hold it, so the
     * top code is one LSB short and the constant has to land there exactly. */
    ASSERT_EQ_INT(sysmon_raw_to_microvolts_supply(65535), 2999954u);
}

TEST(supply_conversion_is_exact_at_half_scale)
{
    ASSERT_EQ_INT(sysmon_raw_to_microvolts_supply(32768), 1500000u);
}

TEST(supply_conversion_does_not_overflow_at_the_top_code)
{
    /* 65535 * 46875 is 3.07e9, past a signed 32-bit int. Done in signed
     * arithmetic this returns a negative voltage. */
    ASSERT_TRUE(sysmon_raw_to_microvolts_supply(65535) > 2000000u);
}

TEST(external_conversion_is_exact_at_half_scale)
{
    /* VP/VN is a 1.0 V range, and 1.0 V is not adjustable -- a pot divider
     * that exceeds it clips rather than scaling. */
    ASSERT_EQ_INT(sysmon_raw_to_microvolts_external(32768), 500000u);
}

TEST(external_conversion_is_exact_at_full_scale)
{
    ASSERT_EQ_INT(sysmon_raw_to_microvolts_external(65535), 999984u);
}

TAP_MAIN_BEGIN
    RUN(locates_the_drp_window_where_this_hardware_puts_it);
    RUN(falls_back_to_the_vendor_drivers_window_when_that_is_the_live_one);
    RUN(rejects_a_window_whose_temperature_reads_zero);
    RUN(rejects_a_window_whose_supply_rails_disagree_with_the_board);
    RUN(reports_not_found_when_every_window_is_silent);
    RUN(prefers_the_measured_window_when_two_of_them_answer);
    RUN(drp_read_addresses_one_word_per_drp_register);
    RUN(drp_read_keeps_only_the_low_sixteen_bits);
    RUN(temperature_converts_at_the_point_ug580_pins_down);
    RUN(temperature_raw_zero_is_the_impossible_reading);
    RUN(temperature_converts_a_cold_reading_below_zero);
    RUN(supply_conversion_is_exact_at_full_scale);
    RUN(supply_conversion_is_exact_at_half_scale);
    RUN(supply_conversion_does_not_overflow_at_the_top_code);
    RUN(external_conversion_is_exact_at_half_scale);
    RUN(external_conversion_is_exact_at_full_scale);
TAP_MAIN_END
