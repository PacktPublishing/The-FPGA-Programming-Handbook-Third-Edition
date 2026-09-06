"""The PS's own SYSMON reader.

This exists so the notebook can check the panel against an independent
measurement of the same sensors. That check is only worth anything if both
sides locate the DRP window by the same rules and convert with the same
constants, so the last class here reads sw_mb/src/sysmon.h and asserts they
have not drifted apart.
"""
import os
import re
import unittest

import sysmon
from fake_mmio import FakeMMIO

HERE = os.path.dirname(os.path.abspath(__file__))
SYSMON_H = os.path.join(HERE, os.pardir, "sw_mb", "src", "sysmon.h")
SYSMON_C = os.path.join(HERE, os.pardir, "sw_mb", "src", "sysmon.c")

RAW_TEMP_42C = 41463
RAW_VCCINT_850 = 18568
RAW_VCCAUX_180 = 39321


def place_healthy(mmio, drp_base):
    mmio.write(drp_base + 4 * sysmon.DRP_TEMPERATURE, RAW_TEMP_42C)
    mmio.write(drp_base + 4 * sysmon.DRP_VCCINT, RAW_VCCINT_850)
    mmio.write(drp_base + 4 * sysmon.DRP_VCCAUX, RAW_VCCAUX_180)


class LocatingTheWindow(unittest.TestCase):
    def setUp(self):
        self.mmio = FakeMMIO(sysmon.AXI_WINDOW_SIZE)

    def test_it_finds_the_window_where_this_hardware_puts_it(self):
        place_healthy(self.mmio, 0x1400)
        s = sysmon.Sysmon(self.mmio)
        self.assertEqual(s.locate(), 0x1400)

    def test_it_falls_back_to_the_vendor_drivers_window(self):
        place_healthy(self.mmio, 0x0400)
        s = sysmon.Sysmon(self.mmio)
        self.assertEqual(s.locate(), 0x0400)

    def test_it_refuses_a_window_reading_zero_for_temperature(self):
        """Raw zero is -280 C. It is the signature of an address that decodes
        to nothing, and it is indistinguishable from a SYSMON that is present
        and not converting -- which is the fault CH13 spent a day on."""
        place_healthy(self.mmio, 0x1400)
        self.mmio.write(0x1400 + 4 * sysmon.DRP_TEMPERATURE, 0)
        s = sysmon.Sysmon(self.mmio)
        with self.assertRaises(sysmon.SysmonNotFound):
            s.locate()

    def test_it_refuses_a_window_whose_rails_disagree_with_the_board(self):
        place_healthy(self.mmio, 0x1400)
        self.mmio.write(0x1400 + 4 * sysmon.DRP_VCCINT, RAW_VCCAUX_180)
        s = sysmon.Sysmon(self.mmio)
        with self.assertRaises(sysmon.SysmonNotFound):
            s.locate()

    def test_it_prefers_the_measured_window_when_two_answer(self):
        place_healthy(self.mmio, 0x1400)
        place_healthy(self.mmio, 0x0400)
        s = sysmon.Sysmon(self.mmio)
        self.assertEqual(s.locate(), 0x1400)

    def test_reading_before_locating_is_refused(self):
        """A read against an assumed window is exactly the mistake this class
        exists to prevent, so it cannot be made by accident."""
        s = sysmon.Sysmon(self.mmio)
        with self.assertRaises(sysmon.SysmonNotFound):
            s.temperature_celsius()


class Conversions(unittest.TestCase):
    def test_temperature_matches_ug580(self):
        self.assertAlmostEqual(sysmon.raw_to_celsius(41463), 41.99945, places=4)

    def test_raw_zero_is_the_impossible_reading(self):
        self.assertAlmostEqual(sysmon.raw_to_celsius(0), -280.23088, places=4)

    def test_supply_full_scale_is_three_volts(self):
        self.assertAlmostEqual(sysmon.raw_to_supply_volts(65535), 2.999954,
                               places=5)

    def test_external_full_scale_is_one_volt(self):
        """VP/VN's range is fixed at 1.0 V and is NOT adjustable, so a pot
        divider that exceeds it clips rather than scaling."""
        self.assertAlmostEqual(sysmon.raw_to_external_volts(65535), 0.999985,
                               places=5)

    def test_the_pot_reads_as_a_fraction_of_full_scale(self):
        self.assertAlmostEqual(sysmon.raw_to_fraction(32768), 0.5, places=6)


class Reading(unittest.TestCase):
    def setUp(self):
        self.mmio = FakeMMIO(sysmon.AXI_WINDOW_SIZE)
        place_healthy(self.mmio, 0x1400)
        self.sysmon = sysmon.Sysmon(self.mmio)
        self.sysmon.locate()

    def test_it_reads_the_temperature(self):
        self.assertAlmostEqual(self.sysmon.temperature_celsius(), 41.99945,
                               places=4)

    def test_it_keeps_only_the_low_sixteen_bits(self):
        self.mmio.write(0x1400 + 4 * sysmon.DRP_VP_VN, 0xFFFF1234)
        self.assertEqual(self.sysmon.drp_read(sysmon.DRP_VP_VN), 0x1234)

    def test_read_all_returns_every_channel_the_display_can_show(self):
        got = self.sysmon.read_all()
        for name in ("vccint", "vccaux", "vccbram"):
            self.assertIn(name, got["supplies"])
        self.assertIn("temperature", got)
        self.assertIn("pot", got)


class AgreementWithTheApplication(unittest.TestCase):
    """The notebook's cross-check compares this module's reading with the
    panel's. If the two sides used different candidate windows or different
    constants, a disagreement would mean nothing."""

    def setUp(self):
        if not (os.path.isfile(SYSMON_H) and os.path.isfile(SYSMON_C)):
            self.skipTest("the application's sysmon sources were not found")
        with open(SYSMON_H) as handle:
            self.text = handle.read()
        # The candidate list is DEFINED in the .c; the header only declares
        # it, so the values are only there.
        with open(SYSMON_C) as handle:
            self.source = handle.read()

    def test_the_candidate_windows_are_the_same_and_in_the_same_order(self):
        body = re.search(
            r"sysmon_drp_candidates\[SYSMON_CANDIDATE_COUNT\]\s*=\s*\{(.*?)\}",
            self.source, re.S).group(1)
        found = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]+)u", body)]
        self.assertEqual(found, list(sysmon.DRP_CANDIDATES))

    def test_the_drp_register_addresses_are_the_same(self):
        for name, value in [("DRP_TEMPERATURE", sysmon.DRP_TEMPERATURE),
                            ("DRP_VCCINT", sysmon.DRP_VCCINT),
                            ("DRP_VCCAUX", sysmon.DRP_VCCAUX),
                            ("DRP_VP_VN", sysmon.DRP_VP_VN),
                            ("DRP_VCCBRAM", sysmon.DRP_VCCBRAM)]:
            found = re.search(r"#define %s\s+0x([0-9A-Fa-f]+)u" % name,
                              self.text).group(1)
            self.assertEqual(int(found, 16), value, name)

    def test_the_plausibility_bounds_are_the_same(self):
        pairs = [("SYSMON_VCCINT_MIN_UV", sysmon.VCCINT_MIN_V),
                 ("SYSMON_VCCINT_MAX_UV", sysmon.VCCINT_MAX_V),
                 ("SYSMON_VCCAUX_MIN_UV", sysmon.VCCAUX_MIN_V),
                 ("SYSMON_VCCAUX_MAX_UV", sysmon.VCCAUX_MAX_V)]
        for name, volts in pairs:
            found = re.search(r"#define %s\s+\((\d+)u?\)" % name,
                              self.text).group(1)
            self.assertAlmostEqual(int(found) / 1e6, volts, places=6, msg=name)


if __name__ == "__main__":
    unittest.main()
