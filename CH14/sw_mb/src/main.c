/* CH14 -- the SYSMON on a Grove 16x2 LCD.
 *
 * Reads the UltraScale+ SYSMON over AXI4-Lite and shows it on a Grove panel
 * over AXI IIC, on a MicroBlaze-V with 64 KB of local memory, no FPU, no
 * interrupt controller and NO CONSOLE.
 *
 * The top row is always the die temperature. The bottom row is whichever
 * reading the board's potentiometer is pointing at, which gives the operator
 * a way to prove the whole chain -- ADC through processor through I2C to
 * glass -- is alive, by turning a knob.
 *
 * Everything this loop learns also goes into `mailbox`, which the PS reads
 * while this runs. See mailbox.h for why that is not optional here. */

#include "mmio.h"
#include "plat.h"
#include "axi_iic.h"
#include "grove_lcd.h"
#include "sysmon.h"
#include "pages.h"
#include "render.h"
#include "mailbox.h"

/* Five refreshes a second. Fast enough that turning the pot feels immediate,
 * slow enough that the panel is not being rewritten while a reader's eye is
 * still on it. One refresh is about 40 ms of I2C at 100 kHz, so the loop
 * spends most of its time waiting. */
#define REFRESH_US 200000u

/* Defined here rather than in a header so there is exactly one, and found by
 * the notebook through the ELF's symbol table rather than at a fixed address
 * that would have to be kept in step with a linker script. */
volatile mailbox_t mailbox;

static void publish(uint32_t status_bits)
{
    mailbox.status |= status_bits;
}

static readings_t take_readings(const sysmon_t *sm)
{
    readings_t r;
    r.temperature_mc = sysmon_raw_to_millicelsius(
        sysmon_drp_read(sm, DRP_TEMPERATURE));
    /* The macro latches these itself since power-up, so a transient does not
     * have to be caught by polling for it. */
    r.temp_min_mc = sysmon_raw_to_millicelsius(
        sysmon_drp_read(sm, DRP_MIN_TEMPERATURE));
    r.temp_max_mc = sysmon_raw_to_millicelsius(
        sysmon_drp_read(sm, DRP_MAX_TEMPERATURE));
    r.vccint_uv  = sysmon_raw_to_microvolts_supply(sysmon_drp_read(sm, DRP_VCCINT));
    r.vccaux_uv  = sysmon_raw_to_microvolts_supply(sysmon_drp_read(sm, DRP_VCCAUX));
    r.vccbram_uv = sysmon_raw_to_microvolts_supply(sysmon_drp_read(sm, DRP_VCCBRAM));
    r.pot_uv     = sysmon_raw_to_microvolts_external(sysmon_drp_read(sm, DRP_VP_VN));
    return r;
}

int main(void)
{
    axi_iic_t   iic;
    grove_lcd_t lcd;
    sysmon_t    sm;
    char top[RENDER_BUF];
    char bottom[RENDER_BUF];
    int page = -1;
    int sysmon_found;

    /* The magic word goes down first. Until it does, whatever the PS reads
     * out of this memory is the previous bitstream's leftovers or the
     * bitstream's own BRAM initialisation -- and "the application has not
     * started" has to be distinguishable from "the application is stuck". */
    mailbox.magic = MAILBOX_MAGIC;
    mailbox.version = MAILBOX_VERSION;
    mailbox.status = 0;
    mailbox.heartbeat = 0;
    mailbox.drp_base = 0;
    mailbox.iic_errors = 0;
    mailbox.last_iic_status = IIC_OK;

    axi_iic_init(&iic, IIC_BASE_ADDR);

    iic_status_t s = grove_lcd_init(&lcd, &iic, LCD_DEFAULT_CONTRAST);
    if (s == IIC_OK) {
        publish(MB_STATUS_LCD_READY);
    } else {
        /* A panel that is not answering cannot report that it is not
         * answering. The mailbox can, and the loop keeps turning so that it
         * does -- stopping here would look identical to a processor that
         * never left reset. */
        publish(MB_STATUS_LCD_FAILED);
        mailbox.last_iic_status = s;
        mailbox.iic_errors++;
    }

    sysmon_init(&sm, SYSMON_BASE_ADDR);
    sysmon_found = (sysmon_locate(&sm) == SYSMON_OK);
    if (sysmon_found) {
        publish(MB_STATUS_SYSMON_LOCATED);
        mailbox.drp_base = sm.drp_base;
    }

    for (;;) {
        if (sysmon_found) {
            readings_t r = take_readings(&sm);
            uint16_t pot_raw = sysmon_drp_read(&sm, DRP_VP_VN);

            page = page_select(page, pot_raw);

            render_top(top, sizeof top, &r);
            render_bottom(bottom, sizeof bottom, &r, page);

            mailbox.temperature_mc = r.temperature_mc;
            mailbox.vp_vn_raw = pot_raw;
            mailbox.page = (uint32_t)page;
        } else {
            render_sysmon_fault(top, bottom, RENDER_BUF);
        }

        s = grove_lcd_write_row(&lcd, 0, top);
        if (s == IIC_OK)
            s = grove_lcd_write_row(&lcd, 1, bottom);
        if (s != IIC_OK) {
            /* Counted, not fatal. A Grove connector nudged loose produces a
             * NACK and then works again; a loop that gave up on the first one
             * would need a power cycle to recover from a wobble. */
            mailbox.iic_errors++;
            mailbox.last_iic_status = s;
        }

        /* Last, so that a heartbeat means a whole refresh completed rather
         * than one having been started. */
        mailbox.heartbeat++;
        plat_delay_us(REFRESH_US);
    }
}
