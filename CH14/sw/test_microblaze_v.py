"""Loading and starting the processor from the PS.

The whole reason build.tcl added an AXI master, a BRAM controller and a reset
GPIO. If any of this is wrong the symptom is a blank panel, so the ordering
rules below are asserted rather than trusted.
"""
import struct
import unittest

import elf
from fake_mmio import FakeMMIO
from microblaze_v import MicroblazeV, MEM_SIZE, CTRL_RESET_BIT, GPIO_DATA

from test_elf import build_elf


class Halting(unittest.TestCase):
    def setUp(self):
        self.bram = FakeMMIO(MEM_SIZE)
        self.ctrl = FakeMMIO(0x10000)
        self.mb = MicroblazeV(self.bram, self.ctrl)

    def test_halt_asserts_the_reset_bit(self):
        self.mb.halt()
        self.assertEqual(self.ctrl.read(GPIO_DATA) & CTRL_RESET_BIT,
                         CTRL_RESET_BIT)

    def test_run_releases_the_reset_bit(self):
        self.mb.halt()
        self.mb.run()
        self.assertEqual(self.ctrl.read(GPIO_DATA) & CTRL_RESET_BIT, 0)

    def test_it_reports_whether_the_processor_is_held(self):
        self.mb.halt()
        self.assertTrue(self.mb.is_halted())
        self.mb.run()
        self.assertFalse(self.mb.is_halted())


class LoadingAnApplication(unittest.TestCase):
    def setUp(self):
        self.bram = FakeMMIO(MEM_SIZE)
        self.ctrl = FakeMMIO(0x10000)
        self.mb = MicroblazeV(self.bram, self.ctrl)

    def test_it_writes_the_segment_into_memory_at_its_address(self):
        image = build_elf([(0x100, b"\xDE\xAD\xBE\xEF", 4)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.assertEqual(self.bram.array[0x100:0x104], b"\xDE\xAD\xBE\xEF")

    def test_it_zero_fills_the_memory_a_segment_claims_beyond_its_bytes(self):
        """.bss. The startup code zeroes it too, but only after it has run --
        and a mailbox left holding the previous run's magic word would say the
        application had started before it had."""
        self.bram.array[0x10:0x20] = b"\xFF" * 16
        image = build_elf([(0x0, b"\x01\x02\x03\x04", 0x20)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.assertEqual(self.bram.array[0x04:0x20], b"\x00" * 28)

    def test_it_refuses_to_load_while_the_processor_is_running(self):
        """Writing a program underneath a running processor produces whatever
        the half-written program happens to do, and this processor has no way
        to report that it has gone wrong."""
        image = build_elf([(0x0, b"\x01\x02\x03\x04", 4)])
        self.mb.run()
        with self.assertRaises(RuntimeError):
            self.mb.load_elf(image)

    def test_it_refuses_a_segment_that_does_not_fit_in_the_memory(self):
        """64 KB of BRAM and no other memory. A segment past the end would
        wrap or fault depending on the interconnect's mood."""
        image = build_elf([(MEM_SIZE - 4, b"\x01\x02\x03\x04\x05\x06\x07\x08", 8)])
        self.mb.halt()
        with self.assertRaises(ValueError):
            self.mb.load_elf(image)

    def test_it_writes_a_segment_whose_length_is_not_a_whole_number_of_words(self):
        """The BRAM controller is 32 bits wide, so a three-byte tail has to be
        merged with what is already there rather than dropped or overrun."""
        image = build_elf([(0x0, b"\xAA\xBB\xCC\xDD\xEE", 5)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.assertEqual(self.bram.array[0:5], b"\xAA\xBB\xCC\xDD\xEE")

    def test_it_writes_a_segment_that_does_not_start_on_a_word_boundary(self):
        image = build_elf([(0x102, b"\xAA\xBB", 2)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.assertEqual(self.bram.array[0x102:0x104], b"\xAA\xBB")

    def test_it_returns_the_symbols_so_the_mailbox_can_be_found(self):
        image = build_elf([(0x0, b"\x01\x02\x03\x04", 4)],
                          symbols=[("mailbox", 0x1FB8)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.assertEqual(self.mb.symbol_address("mailbox"), 0x1FB8)

    def test_loading_does_not_start_the_processor_on_its_own(self):
        """Two steps, deliberately: the caller sets the mailbox up and checks
        what it loaded before letting the processor run."""
        image = build_elf([(0x0, b"\x01\x02\x03\x04", 4)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.assertTrue(self.mb.is_halted())


class ReadingMemoryBack(unittest.TestCase):
    def setUp(self):
        self.bram = FakeMMIO(MEM_SIZE)
        self.ctrl = FakeMMIO(0x10000)
        self.mb = MicroblazeV(self.bram, self.ctrl)

    def test_it_reads_a_block_of_bytes(self):
        self.bram.array[0x40:0x48] = b"01234567"
        self.assertEqual(self.mb.read_memory(0x40, 8), b"01234567")

    def test_it_reads_a_block_that_is_not_word_aligned(self):
        self.bram.array[0x41:0x44] = b"abc"
        self.assertEqual(self.mb.read_memory(0x41, 3), b"abc")

    def test_it_refuses_to_read_past_the_end_of_the_memory(self):
        with self.assertRaises(ValueError):
            self.mb.read_memory(MEM_SIZE - 2, 8)

    def test_verifying_a_load_compares_what_was_written(self):
        """The BRAM is reached over AXI from the PS while the LMB side is
        idle. It should be exact, and the one thing worth knowing early is if
        it is not."""
        image = build_elf([(0x0, bytes(range(64)), 64)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.assertTrue(self.mb.verify_elf(image))

    def test_verifying_reports_memory_that_did_not_take_the_write(self):
        image = build_elf([(0x0, bytes(range(64)), 64)])
        self.mb.halt()
        self.mb.load_elf(image)
        self.bram.array[0x10] ^= 0xFF
        self.assertFalse(self.mb.verify_elf(image))


if __name__ == "__main__":
    unittest.main()
