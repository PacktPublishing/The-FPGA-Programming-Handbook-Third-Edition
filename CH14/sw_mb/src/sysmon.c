#include "sysmon.h"
#include "mmio.h"

/* 0x1400 first: it is where this window was measured, on this IP revision,
 * on this board, by scanning all 8 KB of it. 0x400 is what Vitis's own
 * sysmon driver computes for system_management_wiz, and 0x200 is the
 * 7-series XADC Wizard's. Both are kept so that a different revision moving
 * the window is survivable rather than fatal, and both are tried only after
 * the one that is known to work here. */
const uint32_t sysmon_drp_candidates[SYSMON_CANDIDATE_COUNT] = {
    0x1400u, 0x0400u, 0x0200u
};

void sysmon_init(sysmon_t *s, uintptr_t base)
{
    s->base = base;
    s->drp_base = sysmon_drp_candidates[0];
    s->located = 0;
}

static uint16_t read_at(const sysmon_t *s, uint32_t drp_base, uint32_t address)
{
    /* One 32-bit word per DRP address; the measurement is the low 16 bits,
     * left-justified within them. */
    return (uint16_t)(mmio_read32(s->base, drp_base + 4u * address) & 0xFFFFu);
}

uint16_t sysmon_drp_read(const sysmon_t *s, uint32_t drp_address)
{
    return read_at(s, s->drp_base, drp_address);
}

/* Does this window hold measurements, or is it decoding to nothing?
 *
 * The test is deliberately not "is it non-zero". It is whether the values
 * there agree with three things known WITHOUT asking the SYSMON: silicon is
 * never at -280 C, VCCINT on this board is 0.85 V, and VCCAUX is 1.80 V. A
 * window that satisfies all three is not plausibly a coincidence, and one
 * that satisfies none of them is not a SYSMON however many bits are set. */
static int window_is_live(const sysmon_t *s, uint32_t drp_base)
{
    uint16_t raw_temp = read_at(s, drp_base, DRP_TEMPERATURE);
    if (raw_temp == 0)
        return 0;               /* -280 C: an unmapped read, not a reading */

    int32_t temp_mc = sysmon_raw_to_millicelsius(raw_temp);
    if (temp_mc < SYSMON_PLAUSIBLE_TEMP_MIN_MC ||
        temp_mc > SYSMON_PLAUSIBLE_TEMP_MAX_MC)
        return 0;

    uint32_t vccint = sysmon_raw_to_microvolts_supply(
        read_at(s, drp_base, DRP_VCCINT));
    if (vccint < SYSMON_VCCINT_MIN_UV || vccint > SYSMON_VCCINT_MAX_UV)
        return 0;

    uint32_t vccaux = sysmon_raw_to_microvolts_supply(
        read_at(s, drp_base, DRP_VCCAUX));
    if (vccaux < SYSMON_VCCAUX_MIN_UV || vccaux > SYSMON_VCCAUX_MAX_UV)
        return 0;

    return 1;
}

sysmon_status_t sysmon_locate(sysmon_t *s)
{
    for (int i = 0; i < SYSMON_CANDIDATE_COUNT; i++) {
        if (window_is_live(s, sysmon_drp_candidates[i])) {
            s->drp_base = sysmon_drp_candidates[i];
            s->located = 1;
            return SYSMON_OK;
        }
    }
    s->located = 0;
    return SYSMON_ENOTFOUND;
}

/* 7958 / 1024 approximates 509.3140064 / 65536 degrees per code, and 280231
 * is the offset in millidegrees. The worst error anywhere in the range is
 * under 3 millidegrees -- checked against the floating-point form over all
 * 65536 codes, not assumed -- against a display that shows tenths.
 *
 * The multiply is unsigned and the subtraction signed, because below the
 * offset the result is negative but the product never is. */
int32_t sysmon_raw_to_millicelsius(uint16_t raw)
{
    uint32_t scaled = ((uint32_t)raw * 7958u + 512u) >> 10;
    return (int32_t)scaled - 280231;
}

/* EXACT, and not by luck: 3000000 microvolts over 65536 codes, scaled by
 * 1024, is 3000000 / 64 = 46875 with no remainder.
 *
 * Unsigned throughout. The product at the top code is 3.07e9, which is past
 * INT32_MAX -- done in signed arithmetic this returns a negative voltage. */
uint32_t sysmon_raw_to_microvolts_supply(uint16_t raw)
{
    return ((uint32_t)raw * 46875u) >> 10;
}

/* The external channel's range is a fixed 1.0 V and is NOT adjustable, so a
 * pot divider that exceeds it clips rather than scaling. 1000000 / 64 = 15625,
 * exact for the same reason. */
uint32_t sysmon_raw_to_microvolts_external(uint16_t raw)
{
    return ((uint32_t)raw * 15625u) >> 10;
}
