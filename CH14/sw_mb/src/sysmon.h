/* The UltraScale+ SYSMONE4 behind a System Management Wizard's AXI4-Lite port.
 *
 * WHY THIS DRIVER FINDS ITS OWN REGISTERS
 *
 * Vitis ships a driver for this IP -- sysmon_v7_10 -- and it places the DRP
 * window at 0x400 for system_management_wiz. CH13 scanned the whole 8 KB
 * window on this IP, on this board, on this Vivado version, and found it at
 * 0x1400. The two cannot both be right, and being wrong is invisible: an
 * unmapped read in this window returns zero, which is indistinguishable from
 * a SYSMON that is present, placed, and silently not converting. CH13 lost a
 * day to exactly that.
 *
 * There is no UART on this design, so a wrong guess here would show up as a
 * blank panel and nothing else. So the driver does not guess. It tries each
 * candidate base and accepts one only when the registers there agree with
 * facts known independently of the SYSMON: a temperature that is physically
 * possible, and two supply rails whose voltages are set by the board. */
#ifndef SYSMON_H
#define SYSMON_H

#include <stdint.h>
#include <stddef.h>

/* The wizard's own registers. These answer even when the macro does not,
 * which is how the fault CH13 chased stayed hidden for so long. */
#define SYSMON_SRR       0x00u   /* IP soft reset: write 0x0A */
#define SYSMON_SR        0x04u   /* BUSY, EOC, EOS, current channel */
#define SYSMON_SYSMONRR  0x10u   /* SYSMONE4 macro reset: write 0x0A */

/* DRP register addresses, one 32-bit word each once the window is located. */
#define DRP_TEMPERATURE     0x00u
#define DRP_VCCINT          0x01u
#define DRP_VCCAUX          0x02u
#define DRP_VP_VN           0x03u
#define DRP_VCCBRAM         0x06u
#define DRP_MAX_TEMPERATURE 0x20u
#define DRP_MIN_TEMPERATURE 0x24u

/* Tried in this order. 0x1400 first because it is the one measured on this
 * hardware; the others are the vendor driver's and the 7-series XADC
 * Wizard's, kept so that a different IP revision moving the window is
 * survivable rather than fatal. */
#define SYSMON_CANDIDATE_COUNT 3
extern const uint32_t sysmon_drp_candidates[SYSMON_CANDIDATE_COUNT];

typedef enum {
    SYSMON_OK        =  0,
    SYSMON_ENOTFOUND = -1    /* no candidate window held plausible readings */
} sysmon_status_t;

typedef struct {
    uintptr_t base;
    uint32_t  drp_base;   /* valid only after sysmon_locate returns SYSMON_OK */
    int       located;
} sysmon_t;

void            sysmon_init(sysmon_t *s, uintptr_t base);
sysmon_status_t sysmon_locate(sysmon_t *s);
uint16_t        sysmon_drp_read(const sysmon_t *s, uint32_t drp_address);

/* Conversions, in integers, because this core has no FPU and pulling in
 * soft-float to render two lines of text would be absurd.
 *
 * Both supply constants are EXACT, which is worth noticing rather than
 * treating as luck: 3000000 microvolts over 65536 codes, scaled by 1024, is
 * 3000000/64 = 46875 with no remainder, and the 1.0 V external range gives
 * 1000000/64 = 15625. Only the temperature constant rounds. */
int32_t  sysmon_raw_to_millicelsius(uint16_t raw);
uint32_t sysmon_raw_to_microvolts_supply(uint16_t raw);
uint32_t sysmon_raw_to_microvolts_external(uint16_t raw);

/* The bounds sysmon_locate accepts a candidate window against. */
#define SYSMON_PLAUSIBLE_TEMP_MIN_MC  (-40000)
#define SYSMON_PLAUSIBLE_TEMP_MAX_MC  (125000)
#define SYSMON_VCCINT_MIN_UV          (750000u)
#define SYSMON_VCCINT_MAX_UV          (950000u)
#define SYSMON_VCCAUX_MIN_UV          (1700000u)
#define SYSMON_VCCAUX_MAX_UV          (1900000u)

#endif /* SYSMON_H */
