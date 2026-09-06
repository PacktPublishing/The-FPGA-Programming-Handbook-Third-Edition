"""The sequence the notebook runs, without a board.

from_overlay() needs PYNQ and is exercised on the board by test_on_board.py.
Everything below it is ordering and error handling, which is where the
mistakes that produce a blank panel actually live.
"""
import os
import struct
import tempfile
import unittest

import ch14
import mailbox
import sysmon
from fake_mmio import FakeMMIO
from microblaze_v import MEM_SIZE, GPIO_DATA, CTRL_RESET_BIT
from test_elf import build_elf


MAILBOX_ADDR = 0x800


def mailbox_bytes(heartbeat=7):
    return struct.pack("<IIIIIiIIIi", mailbox.MAGIC, 1, heartbeat, 0x1400,
                       mailbox.STATUS_SYSMON_LOCATED | mailbox.STATUS_LCD_READY,
                       41999, 40000, 2, 0, 0)


def elf_with_mailbox(mailbox_addr=MAILBOX_ADDR):
    """An ELF that reserves room for the mailbox and exports its symbol. The
    struct is left blank, exactly as .bss is in the real one -- the running
    application is what fills it in, which FakeProcessor below models."""
    return build_elf([(0x0, b"\x00" * 0x1000, 0x1000)],
                     symbols=[("mailbox", mailbox_addr)])


class FakeProcessor(FakeMMIO):
    """The mb_ctrl GPIO window, plus the consequence of writing to it.

    A real processor released from reset runs main(), which writes the magic
    word into the mailbox. Without modelling that, the only outcome any test
    could reach is the one where the application never starts -- so this fake
    is what makes the happy path testable at all.
    """

    def __init__(self, bram, mailbox_addr=MAILBOX_ADDR, starts=True):
        super().__init__(0x10000)
        self.bram = bram
        self.mailbox_addr = mailbox_addr
        self.starts = starts
        self.heartbeat = 0
        self.write(GPIO_DATA, CTRL_RESET_BIT)   # powers up held, as the IP does

    def write(self, offset, value):
        super().write(offset, value)
        if offset == GPIO_DATA and not (value & CTRL_RESET_BIT) and self.starts:
            self.heartbeat += 1
            raw = mailbox_bytes(self.heartbeat)
            self.bram.array[self.mailbox_addr:
                            self.mailbox_addr + len(raw)] = raw


class Windows(unittest.TestCase):
    def test_the_expected_addresses_match_the_block_design(self):
        """These four are what build.tcl assigns through M_AXI_HPM0_LPD. If
        the Tcl moves one, this list has to move with it."""
        self.assertEqual(ch14.EXPECTED["mb_bram_ctrl"][0], 0x80000000)
        self.assertEqual(ch14.EXPECTED["mb_ctrl"][0], 0x80010000)
        self.assertEqual(ch14.EXPECTED["axi_iic_0"][0], 0x80020000)
        self.assertEqual(ch14.EXPECTED["system_management_wiz_0"][0], 0x80030000)


class FindingAWindowInTheOverlay(unittest.TestCase):
    """PYNQ splits an overlay's peripherals across TWO dictionaries, and which
    one a peripheral lands in is not obvious from the block design.

    hwh_parser.init_mem_dict() puts any IP whose address segment is a MEMORY
    into mem_dict. An axi_bram_ctrl has one -- its segment is Mem0, not Reg --
    so mb_bram_ctrl goes there, and the device layer then drops it from
    ip_dict. Looking only in ip_dict finds the other three and reports the
    bitstream as wrong, which is the one conclusion that is definitely not
    true: mb_ctrl is in it, and mb_ctrl exists in no other design.
    """

    IP = {
        "axi_iic_0": {"phys_addr": 0x80020000, "addr_range": 0x10000},
        "mb_ctrl": {"phys_addr": 0x80010000, "addr_range": 0x10000},
        "system_management_wiz_0": {"phys_addr": 0x80030000,
                                    "addr_range": 0x10000},
        "zynq_ultra_ps_e_0": {"phys_addr": 0, "addr_range": 0},
    }
    MEM = {
        "mb_bram_ctrl": {"phys_addr": 0x80000000, "addr_range": 0x10000},
    }

    def test_it_finds_a_register_peripheral_in_ip_dict(self):
        found = ch14.find_window(self.IP, self.MEM, "axi_iic_0", 0x80020000)
        self.assertEqual(found["phys_addr"], 0x80020000)

    def test_it_finds_the_bram_controller_in_mem_dict(self):
        """The regression this class exists for."""
        found = ch14.find_window(self.IP, self.MEM, "mb_bram_ctrl", 0x80000000)
        self.assertEqual(found["phys_addr"], 0x80000000)

    def test_it_reports_an_address_that_moved(self):
        """A real drift between the bitstream and sw/, as opposed to PYNQ
        filing the peripheral somewhere else."""
        with self.assertRaises(RuntimeError) as caught:
            ch14.find_window(self.IP, self.MEM, "mb_ctrl", 0x80090000)
        self.assertIn("drifted", str(caught.exception))

    def test_a_genuinely_missing_peripheral_names_both_dictionaries(self):
        """If it really is the wrong bitstream, the error has to list
        everything that was searched -- otherwise the next person repeats the
        half-hour this cost."""
        with self.assertRaises(RuntimeError) as caught:
            ch14.find_window(self.IP, self.MEM, "nonesuch", 0x80000000)
        message = str(caught.exception)
        self.assertIn("axi_iic_0", message)
        self.assertIn("mb_bram_ctrl", message)

    def test_it_survives_an_overlay_with_no_mem_dict_at_all(self):
        """Older PYNQ, or a design with no memory-mapped IP."""
        found = ch14.find_window(self.IP, {}, "axi_iic_0", 0x80020000)
        self.assertEqual(found["phys_addr"], 0x80020000)


class StartingTheApplication(unittest.TestCase):
    def setUp(self):
        self.bram = FakeMMIO(MEM_SIZE)
        self.ctrl = FakeProcessor(self.bram)
        self.iic = FakeMMIO(0x10000)
        self.sysmon_window = FakeMMIO(sysmon.AXI_WINDOW_SIZE)
        self.session = ch14.Ch14(self.bram, self.ctrl, self.iic,
                                 self.sysmon_window)
        self.tmp = tempfile.NamedTemporaryFile(suffix=".elf", delete=False)
        self.tmp.write(elf_with_mailbox())
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_it_returns_the_applications_first_mailbox(self):
        got = self.session.start_application(self.tmp.name, timeout=1.0)
        self.assertEqual(got["drp_base"], 0x1400)
        self.assertIn("sysmon_located", got["status_flags"])

    def test_it_leaves_the_processor_running(self):
        self.session.start_application(self.tmp.name, timeout=1.0)
        self.assertEqual(self.ctrl.read(GPIO_DATA) & CTRL_RESET_BIT, 0)

    def test_it_halts_before_it_writes_anything_to_memory(self):
        """Loading underneath a running processor is the mistake that turns
        into an unreproducible hang, so the order is asserted rather than
        assumed. load_elf refuses outright while the processor runs, so the
        assertion here is that a halt was issued and the release came last."""
        self.session.start_application(self.tmp.name, timeout=1.0)
        reset_values = [value for offset, value in self.ctrl.writes
                        if offset == GPIO_DATA]
        self.assertIn(CTRL_RESET_BIT, reset_values, "never halted")
        self.assertEqual(reset_values[-1] & CTRL_RESET_BIT, 0,
                         "the last thing done should be the release")

    def test_it_stops_the_processor_on_request(self):
        self.session.start_application(self.tmp.name, timeout=1.0)
        self.session.stop_application()
        self.assertTrue(self.session.mb.is_halted())

    def test_it_refuses_an_elf_without_a_mailbox_symbol(self):
        """Without it there is no debug channel at all, and this design has
        no other one."""
        path = self.tmp.name + ".nomailbox"
        with open(path, "wb") as handle:
            handle.write(build_elf([(0x0, b"\x00" * 16, 16)]))
        try:
            with self.assertRaises(RuntimeError) as caught:
                self.session.start_application(path, timeout=0.2)
            self.assertIn("mailbox", str(caught.exception))
        finally:
            os.unlink(path)

    def test_it_reports_an_application_that_never_reaches_main(self):
        """The magic word is blanked before release, so a processor that does
        not start cannot be covered for by a previous run's mailbox."""
        self.ctrl.starts = False
        path = self.tmp.name + ".silent"
        with open(path, "wb") as handle:
            handle.write(elf_with_mailbox())
        try:
            with self.assertRaises(RuntimeError) as caught:
                self.session.start_application(path, timeout=0.3)
            self.assertIn("main()", str(caught.exception))
        finally:
            os.unlink(path)

    def test_a_stale_mailbox_from_a_previous_run_is_not_believed(self):
        """The single most misleading thing this can do is report the last
        run's heartbeat for an application that never started."""
        # A previous run leaves a complete, valid mailbox in BRAM.
        self.bram.array[MAILBOX_ADDR:MAILBOX_ADDR + mailbox.SIZE] = \
            mailbox_bytes(heartbeat=999)
        # This one never reaches main().
        self.ctrl.starts = False
        with self.assertRaises(RuntimeError) as caught:
            self.session.start_application(self.tmp.name, timeout=0.3)
        self.assertIn("main()", str(caught.exception))


class ReadingBack(unittest.TestCase):
    def setUp(self):
        self.bram = FakeMMIO(MEM_SIZE)
        self.session = ch14.Ch14(self.bram, FakeMMIO(0x10000),
                                 FakeMMIO(0x10000),
                                 FakeMMIO(sysmon.AXI_WINDOW_SIZE))

    def test_reading_the_mailbox_before_starting_is_refused(self):
        with self.assertRaises(RuntimeError):
            self.session.read_mailbox()


class TakingThePanel(unittest.TestCase):
    def test_it_halts_the_processor_before_touching_the_bus(self):
        """Two masters on one AXI IIC core interleave into nonsense rather
        than into an error, so this is the only thing preventing it."""
        bram = FakeMMIO(MEM_SIZE)
        session = ch14.Ch14(bram, FakeProcessor(bram), FakeMMIO(0x10000),
                            FakeMMIO(sysmon.AXI_WINDOW_SIZE))
        session.mb.run()
        try:
            session.take_panel()
        except Exception:
            pass                       # the fake bus never acknowledges
        self.assertTrue(session.mb.is_halted())


if __name__ == "__main__":
    unittest.main()
