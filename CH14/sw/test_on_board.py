"""The tests that need the actual board.

    ssh xilinx@192.168.3.1 'cd ~/ch14_sysmon_lcd/sw && \
        /usr/local/share/pynq-venv/bin/python3 -m pytest -q'

Everything else in sw/ runs on a workstation against fakes. These do not:
they download the bitstream, start the application on the MicroBlaze-V, and
check that what it puts on the panel agrees with what the PS reads from the
same sensors. That agreement is the only evidence that the display is showing
measurements rather than plausible-looking numbers.

Skipped rather than failed off the board, so one suite covers both.
"""
import os
import time
import unittest

import ch14
import mailbox
import paths

# Searched rather than fixed: the Jupyter tree and the test harness put out/
# in different places. See sw/paths.py.
BITSTREAM = paths.find_artifact("ch14_sysmon_lcd.bit")
ELF = paths.find_artifact("ch14_sysmon_lcd.elf")


def on_a_board():
    try:
        import pynq  # noqa: F401
    except ImportError:
        return False
    return BITSTREAM is not None and ELF is not None


@unittest.skipUnless(on_a_board(), "not on a board with the artifacts deployed")
class TheApplicationOnTheBoard(unittest.TestCase):
    """One bitstream download for the whole class. Reprogramming the PL
    between tests would cost about a second each and prove nothing extra."""

    @classmethod
    def setUpClass(cls):
        cls.session = ch14.Ch14.from_overlay(BITSTREAM)
        cls.first = cls.session.start_application(ELF)

    @classmethod
    def tearDownClass(cls):
        cls.session.stop_application()

    # --- the processor ---------------------------------------------------

    def test_the_application_reached_main(self):
        self.assertEqual(self.first["version"], mailbox.VERSION)

    def test_the_loop_keeps_turning(self):
        """A heartbeat that stops is the one failure a blank panel cannot be
        distinguished from any other way."""
        before = self.session.read_mailbox()
        time.sleep(1.0)
        after = self.session.read_mailbox()
        self.assertTrue(mailbox.is_alive(before, after),
                        "the heartbeat stopped: the application is loaded and "
                        "no longer running")

    def test_the_heartbeat_advances_at_about_the_rate_it_should(self):
        """REFRESH_US is 200 ms, so a second should be about five. Far fewer
        means the I2C is timing out on every transfer; far more means the
        delay loop is not counting cycles it thinks it is."""
        before = self.session.read_mailbox()["heartbeat"]
        time.sleep(2.0)
        beats = (self.session.read_mailbox()["heartbeat"] - before) & 0xFFFFFFFF
        self.assertGreater(beats, 4)
        self.assertLess(beats, 25)

    # --- the SYSMON ------------------------------------------------------

    def test_the_application_found_the_sysmon(self):
        self.assertIn("sysmon_located", self.first["status_flags"])

    def test_the_application_found_it_where_this_hardware_puts_it(self):
        """0x1400, not the 0x400 Vitis's own driver would have used. If this
        ever fails at 0x400, the IP revision moved the window and both
        sysmon.c and sysmon.py should be re-read before anything else."""
        self.assertEqual(self.session.read_mailbox()["drp_base"], 0x1400)

    def test_the_ps_finds_the_same_window(self):
        self.assertEqual(self.session.sysmon.locate(),
                         self.session.read_mailbox()["drp_base"])

    def test_the_supply_rails_are_what_the_board_is_built_for(self):
        self.session.sysmon.locate()
        self.assertAlmostEqual(self.session.sysmon.supply_volts("vccint"),
                               0.85, delta=0.10)
        self.assertAlmostEqual(self.session.sysmon.supply_volts("vccaux"),
                               1.80, delta=0.10)

    # --- the two sides agreeing ------------------------------------------

    def test_the_temperature_the_application_reports_matches_the_ps(self):
        """Both read the same sensor through the same wizard, moments apart.
        A degree of tolerance covers the gap between the two reads; anything
        larger means one side's conversion is wrong.

        This is the test that makes the panel trustworthy. Without it, a
        display showing 42.0 C proves only that it is showing something."""
        self.session.sysmon.locate()
        from_ps = self.session.sysmon.temperature_celsius()
        from_app = self.session.read_mailbox()["temperature_c"]
        self.assertAlmostEqual(from_app, from_ps, delta=1.0)

    def test_the_pot_the_application_reports_matches_the_ps(self):
        """Raw codes, not volts, so this compares the reading itself rather
        than two conversions of it. The tolerance is generous because the pot
        can be moving."""
        self.session.sysmon.locate()
        from_ps = self.session.sysmon.pot_raw()
        from_app = self.session.read_mailbox()["vp_vn_raw"]
        self.assertAlmostEqual(from_app, from_ps, delta=2000)

    def test_the_page_the_application_shows_follows_the_pot(self):
        """page_select's bands, checked against the hardware that feeds them
        rather than against the unit test's idea of a pot."""
        state = self.session.read_mailbox()
        expected = min(state["vp_vn_raw"] * 5 // 65536, 4)
        self.assertAlmostEqual(state["page"], expected, delta=1)

    # --- the panel -------------------------------------------------------

    def test_the_panel_acknowledged_the_application(self):
        self.assertIn("lcd_ready", self.first["status_flags"])

    def test_the_panel_is_not_accumulating_errors(self):
        """A Grove connector nudged loose NACKs and recovers, so a handful
        over a run is survivable. A count that climbs every refresh is a
        wiring fault, and the panel cannot report that about itself."""
        before = self.session.read_mailbox()["iic_errors"]
        time.sleep(1.0)
        after = self.session.read_mailbox()["iic_errors"]
        self.assertEqual(after, before,
                         "the panel NACKed during a one-second window")


@unittest.skipUnless(on_a_board(), "not on a board with the artifacts deployed")
class ThePanelOnItsOwn(unittest.TestCase):
    """Driving the panel from the PS with the processor halted.

    This is what separates "the panel or its wiring is broken" from "the
    application is broken" -- the distinction that, with no UART anywhere in
    this design, nothing else can make.
    """

    def test_the_panel_answers_the_ps_directly(self):
        session = ch14.Ch14.from_overlay(BITSTREAM)
        lcd = session.take_panel()      # halts the processor first
        lcd.write_row(0, "CH14 panel test")
        lcd.write_row(1, "PS drove this")
        self.assertTrue(session.mb.is_halted())


if __name__ == "__main__":
    unittest.main()
