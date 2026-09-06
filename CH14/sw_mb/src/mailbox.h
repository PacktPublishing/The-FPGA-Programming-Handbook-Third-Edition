/* The application's only way to say anything.
 *
 * THIS DESIGN HAS NO UART. Not on the MDM, not an axi_uartlite -- there is no
 * console, and the panel is both the output device and the thing most likely
 * to be broken. A fault anywhere in initialisation would otherwise present as
 * a blank display and nothing else, with no way to tell a wrong I2C address
 * from a wrong SYSMON window from a processor that never left reset.
 *
 * So the application publishes what it knows into a struct in its own memory,
 * and the PS reads it through mb_bram_ctrl while the application runs. That
 * is the whole debug channel, and it is enough: heartbeat says the loop is
 * turning, drp_base says the SYSMON was found and where, iic_errors says the
 * panel is answering.
 *
 * The notebook finds this struct by looking up the symbol "mailbox" in the
 * ELF it just loaded, so there is no fixed address to keep in step and no
 * linker script to edit. Layout still has to match sw/mailbox.py, and
 * test_mailbox.py asserts the offsets against the values below. */
#ifndef MAILBOX_H
#define MAILBOX_H

#include <stdint.h>

#define MAILBOX_MAGIC   0x43483134u   /* "CH14", little-endian */
#define MAILBOX_VERSION 1u

/* status bits */
#define MB_STATUS_SYSMON_LOCATED 0x01u
#define MB_STATUS_LCD_READY      0x02u
#define MB_STATUS_LCD_FAILED     0x04u

typedef struct {
    uint32_t magic;             /* MAILBOX_MAGIC once the application is up */
    uint32_t version;
    uint32_t heartbeat;         /* one per refresh; stops if the loop stops */
    uint32_t drp_base;          /* the SYSMON window found, 0 if none was */
    uint32_t status;            /* MB_STATUS_* */
    int32_t  temperature_mc;    /* millidegrees Celsius */
    uint32_t vp_vn_raw;         /* the pot, as the SYSMON reports it */
    uint32_t page;              /* which page the pot is selecting */
    uint32_t iic_errors;        /* transfers that did not complete cleanly */
    int32_t  last_iic_status;   /* the most recent iic_status_t */
} mailbox_t;

extern volatile mailbox_t mailbox;

#endif /* MAILBOX_H */
