"""The mailbox layout, which two languages have to agree about.

src/mailbox.h defines the struct the application writes; sw/mailbox.py decodes
it. Nothing enforces that they match except this file, so it asserts the
layout against mailbox.h's own text rather than against a copy of it.
"""
import os
import re
import struct
import unittest

import mailbox

HERE = os.path.dirname(os.path.abspath(__file__))
MAILBOX_H = os.path.join(HERE, os.pardir, "sw_mb", "src", "mailbox.h")


def healthy_bytes(**overrides):
    values = {
        "magic": mailbox.MAGIC,
        "version": 1,
        "heartbeat": 1234,
        "drp_base": 0x1400,
        "status": mailbox.STATUS_SYSMON_LOCATED | mailbox.STATUS_LCD_READY,
        "temperature_mc": 41999,
        "vp_vn_raw": 40000,
        "page": 2,
        "iic_errors": 0,
        "last_iic_status": 0,
    }
    values.update(overrides)
    return struct.pack("<IIIIIiIIIi", *[values[f] for f in mailbox.FIELDS])


class Decoding(unittest.TestCase):
    def test_it_reads_every_field_the_application_publishes(self):
        got = mailbox.decode(healthy_bytes())
        self.assertEqual(got["heartbeat"], 1234)
        self.assertEqual(got["drp_base"], 0x1400)
        self.assertEqual(got["temperature_mc"], 41999)
        self.assertEqual(got["page"], 2)

    def test_a_negative_temperature_survives_the_round_trip(self):
        """temperature_mc is signed in the struct; decoded as unsigned, a cold
        board would read as about four billion millidegrees."""
        got = mailbox.decode(healthy_bytes(temperature_mc=-10000))
        self.assertEqual(got["temperature_mc"], -10000)

    def test_a_negative_iic_status_survives_the_round_trip(self):
        got = mailbox.decode(healthy_bytes(last_iic_status=-1))
        self.assertEqual(got["last_iic_status"], -1)

    def test_it_rejects_a_wrong_magic_word(self):
        """Before the application writes the magic, this memory holds the
        bitstream's BRAM initialisation. Decoding it would report a heartbeat
        of whatever happened to be there -- and 'not started' has to look
        different from 'started and stuck'."""
        with self.assertRaises(ValueError):
            mailbox.decode(healthy_bytes(magic=0))

    def test_it_rejects_a_version_it_does_not_know(self):
        with self.assertRaises(ValueError):
            mailbox.decode(healthy_bytes(version=99))

    def test_it_rejects_a_buffer_that_is_too_short(self):
        with self.assertRaises(ValueError):
            mailbox.decode(healthy_bytes()[:-4])

    def test_it_names_the_status_bits_that_are_set(self):
        got = mailbox.decode(healthy_bytes())
        self.assertIn("sysmon_located", got["status_flags"])
        self.assertIn("lcd_ready", got["status_flags"])
        self.assertNotIn("lcd_failed", got["status_flags"])

    def test_it_converts_the_temperature_for_display(self):
        got = mailbox.decode(healthy_bytes(temperature_mc=41999))
        self.assertAlmostEqual(got["temperature_c"], 41.999, places=3)


class Liveness(unittest.TestCase):
    def test_a_heartbeat_that_advanced_means_the_loop_is_turning(self):
        self.assertTrue(mailbox.is_alive(before={"heartbeat": 10},
                                         after={"heartbeat": 11}))

    def test_a_heartbeat_that_did_not_advance_means_it_is_not(self):
        """The one thing the mailbox can say that nothing else can: the
        application is loaded, the magic is there, and it has stopped."""
        self.assertFalse(mailbox.is_alive(before={"heartbeat": 10},
                                          after={"heartbeat": 10}))

    def test_a_heartbeat_that_wrapped_still_counts_as_alive(self):
        """It is a 32-bit counter at five a second: about 27 years, but the
        arithmetic should not be the thing that breaks."""
        self.assertTrue(mailbox.is_alive(before={"heartbeat": 0xFFFFFFFF},
                                         after={"heartbeat": 0}))


class AgreementWithTheApplication(unittest.TestCase):
    """Read mailbox.h and check this module describes the same struct. Three
    copies of a layout is two too many, but C cannot read Python."""

    def setUp(self):
        if not os.path.isfile(MAILBOX_H):
            self.skipTest("mailbox.h not found")
        with open(MAILBOX_H) as handle:
            self.text = handle.read()

    def test_the_field_order_matches_the_struct(self):
        body = re.search(r"typedef struct\s*\{(.*?)\}\s*mailbox_t;",
                         self.text, re.S).group(1)
        names = re.findall(r"^\s*(?:u?int32_t)\s+(\w+)\s*;", body, re.M)
        self.assertEqual(names, list(mailbox.FIELDS))

    def test_the_signedness_matches_the_struct(self):
        body = re.search(r"typedef struct\s*\{(.*?)\}\s*mailbox_t;",
                         self.text, re.S).group(1)
        pairs = re.findall(r"^\s*(u?int32_t)\s+(\w+)\s*;", body, re.M)
        expected = "<" + "".join("I" if t == "uint32_t" else "i"
                                 for t, _ in pairs)
        self.assertEqual(expected, mailbox.STRUCT_FORMAT)

    def test_the_magic_word_matches(self):
        value = re.search(r"#define MAILBOX_MAGIC\s+0x([0-9A-Fa-f]+)",
                          self.text).group(1)
        self.assertEqual(int(value, 16), mailbox.MAGIC)

    def test_the_status_bits_match(self):
        for name, value in [("MB_STATUS_SYSMON_LOCATED",
                             mailbox.STATUS_SYSMON_LOCATED),
                            ("MB_STATUS_LCD_READY", mailbox.STATUS_LCD_READY),
                            ("MB_STATUS_LCD_FAILED", mailbox.STATUS_LCD_FAILED)]:
            found = re.search(r"#define %s\s+0x([0-9A-Fa-f]+)" % name,
                              self.text).group(1)
            self.assertEqual(int(found, 16), value, name)


if __name__ == "__main__":
    unittest.main()
