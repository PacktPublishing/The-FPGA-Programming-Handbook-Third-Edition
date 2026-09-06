"""Reading what the application has to say.

This design has NO UART, so the struct the application publishes into its own
memory is the entire debug channel. See sw_mb/src/mailbox.h for why, and for
the definition this file has to match -- test_mailbox.py reads that header and
asserts the two agree, because nothing else can.
"""

import struct

MAGIC = 0x43483134       # "CH14", little-endian
VERSION = 1

# In struct order. Signedness matters: temperature_mc and last_iic_status are
# signed, and a cold board decoded as unsigned reads as about four billion
# millidegrees.
FIELDS = (
    "magic",
    "version",
    "heartbeat",
    "drp_base",
    "status",
    "temperature_mc",
    "vp_vn_raw",
    "page",
    "iic_errors",
    "last_iic_status",
)
STRUCT_FORMAT = "<IIIIIiIIIi"
SIZE = struct.calcsize(STRUCT_FORMAT)

STATUS_SYSMON_LOCATED = 0x01
STATUS_LCD_READY = 0x02
STATUS_LCD_FAILED = 0x04

STATUS_NAMES = (
    (STATUS_SYSMON_LOCATED, "sysmon_located"),
    (STATUS_LCD_READY, "lcd_ready"),
    (STATUS_LCD_FAILED, "lcd_failed"),
)

# The pages, in the order pages.h declares them.
PAGE_NAMES = ("VCCINT", "VCCAUX", "VCCBRAM", "POT", "TEMP_RANGE")


def decode(raw):
    """Turn the struct's bytes into a dict, or refuse.

    Refusing on a wrong magic word is the point rather than an inconvenience.
    Before the application writes it, this memory holds whatever the bitstream
    initialised the BRAM to -- and "the application has not started" has to
    look different from "the application started and stopped", which is
    exactly what a heartbeat read out of uninitialised memory would hide.
    """
    if len(raw) < SIZE:
        raise ValueError(f"need {SIZE} bytes of mailbox, got {len(raw)}")

    values = dict(zip(FIELDS, struct.unpack(STRUCT_FORMAT, raw[:SIZE])))

    if values["magic"] != MAGIC:
        raise ValueError(
            f"mailbox magic is 0x{values['magic']:08X}, not 0x{MAGIC:08X}. "
            "The application has not written it, which means it has not "
            "reached main() -- check the ELF loaded and the processor was "
            "released from reset.")
    if values["version"] != VERSION:
        raise ValueError(
            f"mailbox version {values['version']}, expected {VERSION} -- "
            "sw_mb/src/mailbox.h and sw/mailbox.py have drifted apart")

    values["status_flags"] = [name for bit, name in STATUS_NAMES
                              if values["status"] & bit]
    values["temperature_c"] = values["temperature_mc"] / 1000.0
    values["page_name"] = (PAGE_NAMES[values["page"]]
                           if values["page"] < len(PAGE_NAMES) else "?")
    return values


def is_alive(before, after):
    """Did the loop turn between these two reads?

    This is the one thing the mailbox can establish that nothing else here
    can: the application is loaded, its magic is present, and it has stopped.
    A blank panel cannot tell you that.
    """
    return before["heartbeat"] != after["heartbeat"]


def describe(values):
    """One block of text for a notebook cell to print."""
    lines = [
        f"heartbeat        {values['heartbeat']}",
        f"status           {', '.join(values['status_flags']) or 'none'}",
        f"sysmon DRP base  " +
        (f"0x{values['drp_base']:04X}" if values["drp_base"] else "NOT FOUND"),
        f"temperature      {values['temperature_c']:.3f} C",
        f"pot (raw)        {values['vp_vn_raw']}",
        f"page             {values['page']} ({values['page_name']})",
        f"I2C errors       {values['iic_errors']}"
        + (f"  last status {values['last_iic_status']}"
           if values["iic_errors"] else ""),
    ]
    return "\n".join(lines)
